'''
======================
pipeline_cellranger.py
======================


Overview
========

This pipeline performs the following functions:

* Alignment and quantitation of 10x GEX, CITE-seq and VDJ sequencing data.

Usage
=====

See :doc:`Installation</Installation>` and :doc:`Usage</Usage>` for general
information on how to use CGAT pipelines.

Configuration
-------------

The pipeline requires a configured:file:`pipeline_cellranger.yml` file.

Default configuration files can be generated by executing:

   python <srcdir>/pipeline_cellranger.py config


Inputs
------

In addition to the "pipeline_cellranger.yml" file, the pipeline requires two inputs: 

#. a "samples.tsv" file describing the samples 
#. a "libraries.tsv" table containing the sample prefixes, feature type and fastq paths.

(i) samples.tsv
^^^^^^^^^^^^^^^

A table describing the samples and libraries to be analysed. 

It must have the following columns:

* "sample_id" a unique identifier for the biological sample being analysed
* "library_id" is a unique identifier for the sequencing libraries generated from a single channel on a single 10x chip. Use the same "library ID" for Gene Expression, Antibody Capture, VDJ-T and VDJ-B libraries that are generated from the same channel.

Additional arbitrary columns describing the sample metadata should be included
to aid the downstream analysis, for example

* "condition"
* "replicate"
* "timepoint"
* "genotype"
* "age"
* "sex"

For HTO hashing experiments include a column containing details of the hash tag, e.g.

* "hto_id"


(ii) libraries.tsv
^^^^^^^^^^^^^^^^^^

A table that links individual sequencing libraries, library types and
FASTQ file locations.

It must have the following columns:

* "library_id": Must match the library_ids provided in the "samples.tsv" file, for details see above.
* "feature_type": One of "Gene Expression", "Antibody Capture", "VDJ-T" or "VDJ-B". Case sensitive.
* "fastq_path": the location of the folder containing the fastq files
* "sample": this will be passed to the "--sample" parameter of the cellranger pipelines (see: https://support.10xgenomics.com/single-cell-gene-expression/software/pipelines/latest/using/fastq-input). It is only used to match the relevant FASTQ files: it does not have to match the "sample_id" provided in the "samples.tsv" table, and is not used in downstream analysis.
* "chemistry": The 10x reaction chemistry, the options are: 

  * 'auto' for autodetection, 
  * 'threeprime' for Single Cell 3', 
  * 'fiveprime' for  Single Cell 5', 
  * 'SC3Pv1',
  * 'SC3Pv2',
  * 'SC3Pv3', 
  * 'SC5P-PE',
  * 'SC5P-R2' for Single Cell 5', paired-end/R2-only,
  * 'SC-FB' for Single Cell Antibody-only 3' v2 or 5'.
  
  * "expect_cells": An integer specifying the expected number of cells

It is recommended to include the following columns

* "chip": a unique ID for the 10x Chip
* "channel_id": an integer denoting the channel on the chip
* "date": the date the 10x run was performed


Note: Use of the cellranger "--lanes": parameter is not supported. This means that data from all the lanes present in the given location for the given "sample" prefix will be run. This applies for both Gene Expression and VDJ analysis. If you need to analyse data from a single lane, link the data from that lane into a different location. 

Note: To combine sequencing data from different flow cells, add additional rows to the table. Rows with identical "library_id" and "feature_type" are automatically combined by the pipelines. If you are doing this for VDJ data, the data from the different flows cells must be in different folders as explained in the note below.

Note: For V(D)J analysis, if you need to combine FASTQ files that have a different "sample" prefix (i.e. from different flow cells) the FASTQ files with different "sample" prefixes must be presented in separate folders. This is because despite the docs indicating otherwise (https://support.10xgenomics.com/single-cell-vdj/software/pipelines/latest/using/vdj), "cellranger vdj" does not support this:
  --sample prefix1,prefix2 --fastqs all_data/,all_data/
but it does support:
  --sample prefix1,prefix2 --fastqs flow_cell_1/,flow_cell_2/.

Dependencies
------------

This pipeline requires:
* cgat-core: https://github.com/cgat-developers/cgat-core
* cellranger: https://support.10xgenomics.com/single-cell-gene-expression/


Pipeline logic
--------------

The pipeline is designed to:

* map libraries in parallel to speed up analysis
* submit standalone cellranger jobs rather than to use the cellranger cluster 
  mode which can cause problems on HPC clusters that are difficult to debug
* map ADT data with GEX data: so that the ADT analysis takes advantage of GEX cell calls
* map VDJ-T and VDJ-B libraries using the "cellranger vjd" command.

Note: 10x recommends use of "cellranger multi" for mapping libraries from samples with GEX 
and VDJ. This is so that barcodes present in the VDJ results but not the GEX cell calls
can be removed from the VDJ results. Here for simplicity and to maximise parallelisation we use 
"cellranger vdj": it is trivial to remove VDJ barcodes without a GEX overlap downstream. 

Pipeline output
---------------

The pipeline returns:
* the output of cellranger

Code
====

'''

from ruffus import *
from pathlib import Path
import sys
import os
import glob
import sqlite3
import yaml
import  csv

import cgatcore.experiment as E
from cgatcore import pipeline as P
import cgatcore.iotools as IOTools

import pandas as pd
import numpy as np

# import local pipeline utility functions
import cellhub.tasks as T
import cellhub.tasks.cellranger as cellranger
import cellhub.tasks.samples as samples

# -------------------------- Pipeline Configuration -------------------------- #

# Override function to collect config files
P.control.write_config_files = T.write_config_files

# load options from the yml file
P.parameters.HAVE_INITIALIZED = False
PARAMS = P.get_parameters(T.get_parameter_file(__file__))

# set the location of the code directory
PARAMS["cellhub_code_dir"] = Path(__file__).parents[1]


# ----------------------- Read in the samples set -------------------------- #

runCount, runTCR, runBCR = False, False, False

# Only do this when tasks are being executed.
if len(sys.argv) > 1:
    if sys.argv[1] == "make":
        
        S = samples.samples(sample_tsv = PARAMS["sample_table"],
                    library_tsv = PARAMS["library_table"])
        
        if any([x in S.known_feature_library_types  
                for x in S.feature_types]): 
            runCount = True

        if "VDJ-T" in S.feature_types: runTCR = True 
        if "VDJ-B" in S.feature_types: runBCR = True 

# ---------------------------- Pipeline tasks ------------------------------- #

# ########################################################################### #
# ###########################  Count Analysis  ############################## #
# ########################################################################### #

# In this section the pipeline processes the gene expression (GEX) and antibody
# capture, i.e. antibody derived tag (ADT) information.

def count_jobs():

    if not os.path.exists("cellranger.count.dir"):
        os.mkdir("cellranger.count.dir")
    
    for lib in S.feature_barcode_libraries():
    
        csv_path = os.path.join("cellranger.count.dir", lib + ".csv")
    
        if not os.path.exists(csv_path):
            S.write_csv(lib, csv_path)
    
        yield(csv_path, os.path.join("cellranger.count.dir",
                                 lib + ".sentinel"))
    
@active_if(runCount)      
@files(count_jobs)
def count(infile, outfile):
    '''
    Execute the cellranger count pipeline
    '''
    
    t = T.setup(infile, outfile, PARAMS,
                memory=PARAMS["cellranger_localmem"],
                cpu=PARAMS["cellranger_localcores"])

    this_library_id = os.path.basename(infile)[:-len(".csv")]

    library_parameters = S.library_parameters[this_library_id]

    # provide references for the present feature types
    lib_types = S.lib_types(this_library_id)
    transcriptome, feature_ref  = "", ""
    
    if "Gene Expression" in lib_types:
        transcriptome = "--transcriptome=" + PARAMS["gex_reference"]
    
    if "Antibody Capture" in lib_types:
        feature_ref =  "--feature-ref=" + PARAMS["feature_reference"]

    # add read trimming if specified
    r1len, r2len = "", ""

    if PARAMS["gex_r1-length"] != "false":
        r1len = PARAMS["gex_r1-length"]
    
    if PARAMS["gex_r2-length"] != "false":
        r1len = PARAMS["gex_r2-length"]
 
    # deal with flags
    nosecondary, nobam, includeintrons = "", "", ""
    
    if PARAMS["cellranger_nosecondary"]:
        nosecondary = "--nosecondary"
    if PARAMS["cellranger_no-bam"]:
        nobam = "--no-bam"
    if PARAMS["gex_include-introns"]:
        includeintrons = "--include-introns=true"
 
    statement = '''cd cellranger.count.dir;
                    cellranger count
	    	        --id %(this_library_id)s
                    %(transcriptome)s
                    %(feature_ref)s
                    --libraries=../%(infile)s
		            --nopreflight
                    --disable-ui
                    --expect-cells=%(expect_cells)s
                    --chemistry=%(chemistry)s
                    %(nosecondary)s
                    %(nobam)s
                    --localcores=%(cellranger_localcores)s
                    --localmem=%(cellranger_localmem)s
                    %(includeintrons)s
                    %(r1len)s %(r2len)s
                    &> ../%(log_file)s
                 ''' % dict(PARAMS, 
                            **library_parameters,
                            **t.var, 
                            **locals())

    P.run(statement, **t.resources)
    IOTools.touch_file(outfile)

@active_if(runCount)
@transform(count,
           regex(r"(.*)/(.*).sentinel"),
           r"\1/\2.mtx.register.sentinel")
def mtxAPI(infile, outfile):
    '''
    Register the count market matrix (mtx) files on the API endpoint
    
    Inputs:

    The input cellranger count folder layout is:

    unfiltered "outs": ::
        library_id/outs/raw_feature_bc_matrix [mtx]
        library_id/outs/raw_feature_bc_matrix.h5

    filtered "outs": :: 
        library_id/outs/filtered_feature_bc_matrix
        library_id/outs/filtered_feature_bc_matrix.h5
    
    '''

    # 1. register the GEX, ADT and HTO count matrices

    x = T.api("cellranger")

    mtx_template = {"barcodes": {"path":"path/to/barcodes.tsv",
                                 "format": "tsv",
                                 "description": "cell barcode file"},
                    "features": {"path":"path/to/features.tsv",
                                  "format": "tsv",
                                  "description": "features file"},
                     "matrix": {"path":"path/to/matrix.mtx",
                                 "format": "market-matrix",
                                 "description": "Market matrix file"}
                     }


    library_id = os.path.basename(infile)[:-len(".sentinel")]

    # 1. deal with unfiltered count data
    matrix_location = os.path.join("cellranger.count.dir", library_id,
                                   "outs/raw_feature_bc_matrix")


    to_register = {0:{"type": "unfiltered", 
                      "path": matrix_location, 
                      "id": library_id}}

    # 2. deal with the filtered data
    matrix_location = os.path.join("cellranger.count.dir", library_id,
                                   "outs/filtered_feature_bc_matrix")

    to_register[1] = {"type": "filtered", 
                        "path": matrix_location, 
                        "id": library_id}
    
    
    for key, mtx in to_register.items():

        mtx_loc = to_register[key]["path"]
        subset = to_register[key]["type"]
        id = to_register[key]["id"]

        if os.path.exists(mtx_loc):

            mtx_x = mtx_template.copy()
            mtx_x["barcodes"]["path"] = os.path.join(mtx_loc, "barcodes.tsv.gz")
            mtx_x["features"]["path"] = os.path.join(mtx_loc, "features.tsv.gz")
            mtx_x["matrix"]["path"] =  os.path.join(mtx_loc, "matrix.mtx.gz")

            x.define_dataset(analysis_name="counts",
                             data_subset=subset,
                             data_id=id,
                             data_format="mtx",
                             file_set=mtx_x,
                             analysis_description="Cellranger count GEX output")

            x.register_dataset()
        else:
            raise ValueError("matrix path:'" + mtx_loc + "' does not exist!")

    IOTools.touch_file(outfile)

@active_if(runCount)
@transform(count,
           regex(r"(.*)/(.*).sentinel"),
           r"\1/\2.h5.register.sentinel")
def h5API(infile, outfile):
    '''
    Put the h5 files on the API
    '''
    x = T.api("cellranger")

    out_dir = os.path.dirname(outfile)

    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    library_id = os.path.basename(infile)[:-len(".sentinel")]

    h5_template = {"h5": {"path":"path/to/barcodes.tsv",
                                 "format": "h5",
                                 "link_name": "data.h5",
                                 "description": "10X h5 count file"}}

    # 1. deal with unfiltered count data
    h5_location = os.path.join("cellranger.count.dir", library_id,
                               "outs/raw_feature_bc_matrix.h5")

    h5_x = h5_template.copy()
    h5_x["h5"]["path"] = h5_location

    x.define_dataset(analysis_name="counts",
                     data_subset="unfiltered",
                     data_id=library_id,
                     data_format="h5",
                     file_set=h5_x,
                     analysis_description="Cellranger h5 file")


    x.register_dataset()


    # 2. deal with per sample libraries
    h5_location = os.path.join("cellranger.count.dir", library_id,
                               "outs/filtered_feature_bc_matrix.h5")

    h5_x = h5_template.copy()
    h5_x["h5"]["path"] = h5_location

    x.define_dataset(analysis_name="counts",
                     data_subset="filtered",
                     data_id=library_id,
                     data_format="h5",
                     file_set=h5_x,
                     analysis_description="Cellranger h5 file")

    x.register_dataset()
    IOTools.touch_file(outfile)


# ########################################################################### #
# ############################  TCR Analysis  ############################### #
# ########################################################################### #

# In this section the pipeline performs the V(D)J-T analysis.



def tcr_jobs():

    for lib in S.vdj_t_libraries():
        
        yield(None, os.path.join("cellranger.vdj.t.dir",
                                 lib + ".sentinel"))

@active_if(runTCR)  
@files(tcr_jobs)
def tcr(infile, outfile):
    '''
    Execute the cellranger vdj pipeline for the TCR libraries
    '''
    
    t = T.setup(infile, outfile, PARAMS,
                memory=PARAMS["cellranger_localmem"],
                cpu=PARAMS["cellranger_localcores"])

    library_id = os.path.basename(outfile)[:-len(".sentinel")]

    inner=""
    if PARAMS["vdj_t_inner-enrichment-primers"]:
        inner="--inner-enrichment-primers=" + PARAMS["vdj_t_inner-enrichment-primers"]
    
    sample_dict = S.get_samples_and_fastqs(library_id,"VDJ-T")
 
    statement = '''cd cellranger.vdj.t.dir;
                    cellranger vdj
                    --chain=TR
	    	        --id=%(library_id)s
                    --fastqs=%(fastq_path)s
                    --sample=%(sample)s
                    --reference=%(vdj_t_reference)s
		            --nopreflight
                    --disable-ui
                    --localcores=%(cellranger_localcores)s
                    --localmem=%(cellranger_localmem)s
                    %(inner)s
                    &> ../%(log_file)s
                 ''' % dict(PARAMS, 
                            **t.var, 
                            **sample_dict,
                            **locals())

    P.run(statement, **t.resources)
    IOTools.touch_file(outfile)

@active_if(runTCR)  
@transform(tcr,
           regex(r"(.*)/(.*).sentinel"),
           r"\1/\2.tcr.register.sentinel")
def registerTCR(infile, outfile):
    '''
    Register the TCR contigfiles on the API endpoint
    '''

    x = T.api("cellranger")

    vdj_template = {"contig_annotations": {"path":"path/to/annotations.csv",
                                           "format": "csv",
                                           "description": "per-cell contig annotations"}}

    library_id = os.path.basename(infile[:-len(".sentinel")])

    for data_subset in ["unfiltered", "filtered"]:

        if data_subset == "filtered":
            fn = "filtered_contig_annotations.csv"
            prefix = "filtered"
        elif data_subset == "unfiltered":
            fn = "all_contig_annotations.csv"
            prefix = "all"

        vdj_x = vdj_template.copy()
        vdj_x["contig_annotations"]["path"] = os.path.join("cellranger.vdj.t.dir",
                                                           library_id,"outs",fn)

        x.define_dataset(analysis_name="vdj_t",
                    data_subset=data_subset,
                    data_id=library_id,
                    file_set=vdj_x,
                    analysis_description="cellranger VDJ T contig annotations")

        x.register_dataset()
        
    IOTools.touch_file(outfile)

# ---------------------------< merged TCR contig annotations >------------------------------ #

@active_if(runTCR)  
@merge(tcr,
       "cellranger.vdj.t.dir/out.dir/merged.tcr.sentinel")
def mergeTCR(infiles, outfile):
    '''
    Merge the TCR contig annotations
    '''
    
    t = T.setup(infiles[0], outfile, PARAMS)

    statements = []
    for ann in ["filtered_contig_annotations.csv", 
                "all_contig_annotations.csv"]:
    
        table_paths = " ".join([os.path.join(x[:-len(".sentinel")],
                                             "outs", ann)
                                for x in infiles])

        table_file = os.path.join(t.outdir, ann.replace(".csv",".tsv") + ".gz")

        statement = '''python -m cgatcore.tables
                            --regex-filename ".*/(.*)/.*/.*"
                            --cat "library_id"
                            %(table_paths)s
                    | grep -v "^#" | sed 's/,/\\t/g'
                    | gzip -c
                    > %(table_file)s
                ''' % locals()

        statements.append(statement)
    
    P.run(statements)
    
    IOTools.touch_file(outfile)

@active_if(runTCR)  
@files(mergeTCR, 
       "cellranger.vdj.t.dir/out.dir/merged.tcr.register.sentinel")
def registerMergedTCR(infile, outfile):
    '''
    Register the merged TCR contigfiles on the API endpoint
    '''

    x = T.api("cellranger")

    vdj_template = {"contig_annotations": {"path":"path/to/annotations.csv",
                                           "format": "tsv",
                                           "description": "per-cell contig annotations"}}

    library_id = os.path.basename(infile[:-len(".sentinel")])

    for data_subset in ["unfiltered", "filtered"]:

        if data_subset == "filtered":
            fn = "filtered_contig_annotations.tsv.gz"
            prefix = "filtered"
        elif data_subset == "unfiltered":
            fn = "all_contig_annotations.tsv.gz"
            prefix = "all"

        vdj_x = vdj_template.copy()
        vdj_x["contig_annotations"]["path"] = os.path.join("cellranger.vdj.t.dir",
                                                           "out.dir",fn)

        x.define_dataset(analysis_name="vdj_t_merged",
                    data_subset=data_subset,
                    file_set=vdj_x,
                    analysis_description="Merged cellranger VDJ T contig annotations")

        x.register_dataset()
        
    IOTools.touch_file(outfile)


# ########################################################################### #
# ############################  BCR Analysis  ############################### #
# ########################################################################### #

# In this section the pipeline performs the V(D)J B analysis.

def bcr_jobs():

    for lib in S.vdj_b_libraries():
        
        yield(None, os.path.join("cellranger.vdj.b.dir",
                                 lib + ".sentinel"))


@active_if(runBCR)     
@files(bcr_jobs)
def bcr(infile, outfile):
    '''
    Execute the cellranger vdj pipeline for the BCR libraries
    '''
    
    t = T.setup(infile, outfile, PARAMS,
                memory=PARAMS["cellranger_localmem"],
                cpu=PARAMS["cellranger_localcores"])

    library_id = os.path.basename(outfile)[:-len(".sentinel")]

    inner=""
    if PARAMS["vdj_b_inner-enrichment-primers"]:
        inner="--inner-enrichment-primers=" + PARAMS["vdj_b_inner-enrichment-primers"]
    
    sample_dict = S.get_samples_and_fastqs(library_id,"VDJ-B")
 
    statement = '''cd cellranger.vdj.b.dir;
                    cellranger vdj
                    --chain=IG
	    	        --id=%(library_id)s
                    --fastqs=%(fastq_path)s
                    --sample=%(sample)s
                    --reference=%(vdj_b_reference)s
		            --nopreflight
                    --disable-ui
                    --localcores=%(cellranger_localcores)s
                    --localmem=%(cellranger_localmem)s
                    %(inner)s
                    &> ../%(log_file)s
                 ''' % dict(PARAMS, 
                            **t.var, 
                            **sample_dict,
                            **locals())

    P.run(statement, **t.resources)
    IOTools.touch_file(outfile)

@active_if(runBCR)
@transform(bcr,
           regex(r"(.*)/(.*).sentinel"),
           r"\1/\2.bcr.register.sentinel")
def registerBCR(infile, outfile):
    '''
    Register the individual BCR contigfiles on the API endpoint
    '''

    x = T.api("cellranger")

    vdj_template = {"contig_annotations": {"path":"path/to/annotations.csv",
                                           "format": "csv",
                                           "description": "per-cell contig annotations"}}

    library_id = os.path.basename(infile[:-len(".sentinel")])

    for data_subset in ["unfiltered", "filtered"]:

        if data_subset == "filtered":
            fn = "filtered_contig_annotations.csv"
            prefix = "filtered"
        elif data_subset == "unfiltered":
            fn = "all_contig_annotations.csv"
            prefix = "all"

        vdj_x = vdj_template.copy()
        vdj_x["contig_annotations"]["path"] = os.path.join("cellranger.vdj.b.dir",
                                                           library_id,"outs",fn)

        x.define_dataset(analysis_name="vdj_b",
                    data_subset=data_subset,
                    data_id=library_id,
                    file_set=vdj_x,
                    analysis_description="cellranger VDJ B contig annotations")

        x.register_dataset()
        
    IOTools.touch_file(outfile)

# ---------------------------< merged BCR contig annotations >------------------------------ #

@active_if(runBCR)     
@merge(bcr,
       "cellranger.vdj.b.dir/out.dir/merged.bcr.sentinel")
def mergeBCR(infiles, outfile):
    '''
    Merge the BCR contigfiles
    '''
    
    t = T.setup(infiles[0], outfile, PARAMS)

    statements = []
    for ann in ["filtered_contig_annotations.csv", 
                "all_contig_annotations.csv"]:
    
        table_paths = " ".join([os.path.join(x[:-len(".sentinel")],
                                             "outs", ann)
                                for x in infiles])

        table_file = os.path.join(t.outdir, ann.replace(".csv",".tsv") + ".gz")

        statement = '''python -m cgatcore.tables
                            --regex-filename ".*/(.*)/.*/.*"
                            --cat "library_id"
                            %(table_paths)s
                    | grep -v "^#" | sed 's/,/\\t/g'
                    | gzip -c
                    > %(table_file)s
                ''' % locals()

        statements.append(statement)
    
    P.run(statements)
    
    IOTools.touch_file(outfile)

@active_if(runBCR)
@files(mergeBCR, 
       "cellranger.vdj.b.dir/out.dir/merged.bcr.register.sentinel")
def registerMergedBCR(infile, outfile):
    '''
    Register the merged VDJ-B contigfiles on the API endpoint
    '''

    x = T.api("cellranger")

    vdj_template = {"contig_annotations": {"path":"path/to/annotations.csv",
                                           "format": "tsv",
                                           "description": "per-cell contig annotations"}}

    library_id = os.path.basename(infile[:-len(".sentinel")])

    for data_subset in ["unfiltered", "filtered"]:

        if data_subset == "filtered":
            fn = "filtered_contig_annotations.tsv.gz"
            prefix = "filtered"
        elif data_subset == "unfiltered":
            fn = "all_contig_annotations.tsv.gz"
            prefix = "all"

        vdj_x = vdj_template.copy()
        vdj_x["contig_annotations"]["path"] = os.path.join("cellranger.vdj.b.dir",
                                                           "out.dir",fn)

        x.define_dataset(analysis_name="vdj_b_merged",
                    data_subset=data_subset,
                    #data_id=library_id,
                    file_set=vdj_x,
                    analysis_description="Merged cellranger VDJ B contig annotations")

        x.register_dataset()
        
    IOTools.touch_file(outfile)


# ---------------------------< Pipeline targets >------------------------------ #

@follows(count, 
         mtxAPI, h5API, 
         registerTCR, registerBCR,
         registerMergedBCR, registerMergedTCR)
def full():
    '''
    Run the full pipeline.
    '''
    pass


@follows(mtxAPI, h5API)
@files(None,"use.cellranger.sentinel")
def useCounts(infile, outfile):
    '''
        Set the cellranger counts as the source for downstream analysis.
        This task is not run by default.
    '''
    
    if os.path.exists("api/counts"):
        raise ValueError("Counts have already been registered to the API")

    else:
        os.symlink("cellranger/counts", "api/counts")


def main(argv=None):
    if argv is None:
        argv = sys.argv
    P.main(argv)

if __name__ == "__main__":
    sys.exit(P.main(sys.argv))
