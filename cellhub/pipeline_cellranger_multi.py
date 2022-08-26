'''
============================
pipeline_cellranger_multi.py
============================


Overview
========

This pipeline performs the following functions:

* Alignment and quantitation (using cellranger count or cellranger multi)

Usage
=====

See :doc:`Installation</Installation>` and :doc:`Usage</Usage>` on general
information how to use CGAT pipelines.

Configuration
-------------

The pipeline requires a configured :file:`pipeline_cellranger_multi.yml` file.

Default configuration files can be generated by executing:

   python <srcdir>/pipeline_cellranger_multi.py config


Dependencies
------------

This pipeline requires:
* cgat-core: https://github.com/cgat-developers/cgat-core
* cellranger: https://support.10xgenomics.com/single-cell-gene-expression/


Pipeline output
---------------

The pipeline returns:
* the output of cellranger multi

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

# -------------------------- Pipeline Configuration -------------------------- #

# Override function to collect config files
P.control.write_config_files = T.write_config_files

# load options from the yml file
P.parameters.HAVE_INITIALIZED = False
PARAMS = P.get_parameters(T.get_parameter_file(__file__))

# set the location of the code directory
PARAMS["cellhub_code_dir"] = Path(__file__).parents[1]

# ----------------------- < helper functions > ------------------------ #


@files(None, "task.summary.table.tex")
def taskSummary(infile, outfile):
    '''Make a summary of optional tasks that will be run'''

    tasks, run = [], []

    for k,v in PARAMS.items():
        if k.startswith("run_"):
            tasks.append(k[4:])
            run.append(str(v))

    tab = pd.DataFrame(list(zip(tasks,run)),columns=["task","run"])

    tab.to_latex(buf=outfile, index=False)



# ########################################################################### #
# ################ Read parameters and create config file ################### #
# ########################################################################### #

@active_if(PARAMS["input"] == "mkfastq")
@follows(mkdir("cellranger.multi.dir"))
@originate("cellranger.multi.dir/config.sentinel")
def config(outfile):
    '''
    Read parameters from yml file for the whole experiment and save 
    per-library config files as csv.
    '''

    # check if references exist
    if PARAMS["run_gene-expression"]:
        gexref = PARAMS["gene-expression_reference"]
        if gexref is None:
            raise ValueError('"gene-expression_reference" parameter not set'
                             ' in file "pipeline.yml"')

        if not os.path.exists(gexref):
            raise ValueError('The specified "gene-expression_reference"'
                             ' file does not exist')
    else:
        pass

    if PARAMS["run_feature"]:
        featureref = PARAMS["feature_reference"]
        if featureref is None:
            raise ValueError('"feature_reference" parameter not set'
                             ' in file "pipeline.yml"')

        if not os.path.exists(featureref):
            raise ValueError('The specified "feature_reference"'
                             ' file does not exist')
    else:
        pass

    if PARAMS["run_vdj"]:
        vdjref = PARAMS["vdj_reference"]
        if vdjref is None:
            raise ValueError('"vdj_reference" parameter not set'
                             ' in file "pipeline.yml"')

        if not os.path.exists(vdjref):
            raise ValueError('The specified "vdj_reference"'
                             ' file does not exist')
    else:
        pass


    # read parameters for gex
    section, param = [], []

    if PARAMS["run_gene-expression"]:
        for k,v in PARAMS.items():
            if k.startswith("gene-expression_"):
                if v is not None:
                    section.append(k[16:])
                    param.append(str(v))

        df_gex = pd.DataFrame(list(zip(section,param)),columns=["[gene-expression]",""])
    else:
        pass

    # read parameters for feature
    section, param = [], []

    if PARAMS["run_feature"]:
        for k,v in PARAMS.items():
            if k.startswith("feature_"):
                if v is not None:
                    section.append(k[8:])
                    param.append(str(v))

        df_feature = pd.DataFrame(list(zip(section,param)),columns=["[feature]",""])
    else:
        pass

    # read parameters for vdj
    section, param = [], []

    if PARAMS["run_vdj"]:
        for k,v in PARAMS.items():
            if k.startswith("vdj_"):
                if v is not None:
                    section.append(k[4:])
                    param.append(str(v))

        df_vdj = pd.DataFrame(list(zip(section,param)),columns=["[vdj]",""])
    else:
        pass

    # read parameters for libraries:
    lib_params = PARAMS["libraries"]
    library_ids = list(lib_params.keys())

    for library_id in library_ids:

        # Save subsections of parameters in config files specific for each sample
        # (data.dir/sample01.csv data.dir/sample02.csv etc)
        libsample_params = PARAMS["libraries_" + library_id]

        filename = "cellranger.multi.dir/" + library_id + ".csv"

        lib_df = pd.DataFrame(libsample_params)

        lib_df.drop('description', axis=1, inplace=True)

        lib_columns = list(lib_df)

        smp_df = pd.DataFrame()
        for i in lib_columns:
            tmp = lib_df[i].str.split(',', expand=True)
            #smp_df = smp_df.append(tmp.T)
            smp_df = pd.concat([smp_df, tmp.T])

            # filter out gex rows from libraries table if run_gene-expression = false
            mask = smp_df.feature_types == 'Gene Expression'
            if PARAMS["run_gene-expression"]:
                df_filt = smp_df
            else:
                df_filt = smp_df[~mask]

            # filter out feature rows from libraries table if run_feature = false
            mask = df_filt.feature_types == 'Antibody Capture'
            if PARAMS["run_feature"]:
                df_filt = df_filt
            else:
                df_filt = df_filt[~mask]

            # filter out vdj rows from libraries table if run_vdj = false
            mask = df_filt.feature_types == 'VDJ-B'
            if PARAMS["run_vdj"]:
                df_filt = df_filt
            else:
                df_filt = df_filt[~mask]


        # but I need to add different headers for each subsection, so I stream each table individually.
        with open(filename, 'a') as csv_stream:

            if PARAMS["run_gene-expression"]:
                csv_stream.write('[gene-expression]\n')
                df_gex.to_csv(csv_stream, header=False, index=False)
                csv_stream.write('\n')
            else:
                pass

            if PARAMS["run_feature"]:
                csv_stream.write('[feature]\n')
                df_feature.to_csv(csv_stream, header=False, index=False)
                csv_stream.write('\n')
            else:
                pass

            if PARAMS["run_vdj"]:
                csv_stream.write('[vdj]\n')
                df_vdj.to_csv(csv_stream, header=False, index=False)
                csv_stream.write('\n')
            else:
                pass

            csv_stream.write('[libraries]\n')
            df_filt.to_csv(csv_stream, header=True, index=False)
            csv_stream.write('\n')

    IOTools.touch_file(outfile)

# ########################################################################### #
# ############################ run cellranger multi ######################### #
# ########################################################################### #

def cellrangerMultiJobs():

    csv_files = glob.glob("cellranger.multi.dir/*.csv")
    
    for csv_file in csv_files:
    
        library_id = os.path.basename(csv_file).replace(".csv", "")
        
        outfile = os.path.join("cellranger.multi.dir", 
                               library_id + "-cellranger.multi.sentinel")
        
        yield  [csv_file, outfile]


@follows(config)
@files(cellrangerMultiJobs)
def cellrangerMulti(infile, outfile):
    '''
    Execute the cellranger multi pipeline for first sample.
    '''

    # read id_tag from file name
    config_path = os.path.basename(infile)
    sample_basename = os.path.basename(infile)
    sample_name_sections = sample_basename.split(".")
    id_tag = sample_name_sections[0]


    #set the maximum number of jobs for cellranger
    max_jobs = PARAMS["cellranger_maxjobs"]

    ## send one job script to slurm queue which arranges cellranger run
    ## hard-coded to ensure enough resources
    job_threads = 6
    job_memory = "24G"

    log_file = id_tag + ".log"

    mempercore = PARAMS["cellranger_mempercore"]

    if mempercore:
        mempercore_stat="--mempercore " + str(mempercore)
    else:
        mempercore_stat = ""

    # this statement is to run in slurm mode
    statement = '''cd cellranger.multi.dir;
                    cellranger multi
	    	        --id %(id_tag)s
                    --csv=%(config_path)s
                    --jobmode=%(cellranger_job_template)s
                    --maxjobs=%(max_jobs)s
		            --nopreflight
                    --disable-ui
                    %(mempercore_stat)s
                    &> %(log_file)s
                 '''

    P.run(statement)
    IOTools.touch_file(outfile)


@transform(cellrangerMulti,
           regex(r"(.*)/(.*)-cellranger.multi.sentinel"),
           r"\1/register.mtx.sentinel")
def mtxAPI(infile, outfile):
    '''
    Register the post-processed mtx files on the API endpoint
    
    Inputs:

    The input cellranger.multi.dir folder layout is:

    unfiltered "outs": ::
        library_id/outs/multi/count/raw_feature_bc_matrix/

    filtered "outs": :: 
        library_id/outs/per_sample_outs/sample|library_id/count/sample_feature_bc_matrix
    
    '''

    # 1. register the GEX, ADT and HTO count matrices

    x = T.api("cellranger.multi")

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


    library_id = os.path.basename(infile).split("-cellranger.multi")[0]

    # 1. deal with unfiltered count data
    matrix_location = os.path.join("cellranger.multi.dir", library_id,
                                   "outs/multi/count/raw_feature_bc_matrix")

    idx = 0
    to_register = {idx:{"type":"unfiltered", 
                        "path":matrix_location, 
                        "id": library_id}}

    # 2. deal with the filtered data
    
    # 2. deal with per sample libraries
    per_sample_loc = os.path.join("cellranger.multi.dir",
                                  library_id,
                                  "outs/per_sample_outs/")

    per_sample_dirs = glob.glob(per_sample_loc + "*")

    for per_sample_dir in per_sample_dirs:

        matrix_location = os.path.join(per_sample_dir,
                                       "count/sample_filtered_feature_bc_matrix")

        sample_or_library_id = os.path.basename(per_sample_dir)

        idx += 1
        to_register[idx] = {"type":"filtered",
                            "path":matrix_location,
                            "id": sample_or_library_id}
    
    
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

    IOTools.touch_file(outfile)



@transform(cellrangerMulti,
           regex(r"(.*)/(.*)-cellranger.multi.sentinel"),
           r"\1/register.h5.sentinel")
def h5API(infile, outfile):
    '''
    Put the h5 files on the API

    Inputs:

        The input cellranger.multi.dir folder layout is:

        unfiltered "outs": ::

            library_id/outs/multi/count/raw_feature_bc_matrix/

        filtered "outs": ::

            library_id/outs/per_sample_outs/sample|library_id/count/sample_filtered_feature_bc_matrix

    '''
    x = T.api("cellranger.multi")

    out_dir = os.path.dirname(outfile)

    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    library_id = os.path.basename(infile).split("-cellranger.multi")[0]

    h5_template = {"h5": {"path":"path/to/barcodes.tsv",
                                 "format": "h5",
                                 "link_name": "data.h5",
                                 "description": "10X h5 count file"}}

    # 1. deal with unfiltered count data
    h5_location = os.path.join("cellranger.multi.dir", library_id,
                                   "outs/multi/count/raw_feature_bc_matrix.h5")

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
    per_sample_loc = os.path.join("cellranger.multi.dir",
                                  library_id,
                                  "outs/per_sample_outs/")

    per_sample_dirs = glob.glob(per_sample_loc + "*")

    for per_sample_dir in per_sample_dirs:

        h5_location = os.path.join(per_sample_dir,
                                       "count/sample_filtered_feature_bc_matrix.h5")

        h5_x = h5_template.copy()
        h5_x["h5"]["path"] = h5_location

        sample_id = os.path.basename(per_sample_dir)

        x.define_dataset(analysis_name="counts",
                         data_subset="filtered",
                         data_id=sample_id,
                         data_format="h5",
                         file_set=h5_x,
                         analysis_description="Cellranger h5 file")


        x.register_dataset()

    IOTools.touch_file(outfile)


@transform(cellrangerMulti,
           regex(r"(.*)/(.*)-cellranger.multi.sentinel"),
           r"\1/out.dir/\2/post.process.vdj.sentinel")
def postProcessVDJ(infile, outfile):
    '''
    Post-process the cellranger contig annotations.

    The cellbarcodes are reformatted to the "UMI-LIBRARY_ID" syntax.

    Inputs:

        The input cellranger.multi.dir folder layout is:

        unfiltered "outs": ::
            library_id/outs/multi/vdj_[b|t]/

        filtered "outs": ::
            library_id/outs/per_sample_outs/sample|library_id/vdj_[b|t]/

    Outputs:

        This task produces:

        unfiltered: ::
            out.dir/library_id/unfiltered/vdj_[t|b]/

        filtered: ::
            out.dir/library_id/filtered/sample_id/vdj_[t|b]/

    '''


    out_dir = os.path.dirname(outfile)

    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    library_id = os.path.basename(infile).split("-cellranger.multi")[0]

    vdj_types = ["vdj_b", "vdj_t"]

    for vdj_type in vdj_types:

        if os.path.exists(os.path.join("cellranger.multi.dir", library_id,
                                       "outs/multi/", vdj_type)):

            # 1. deal with unfiltered contig assigments
            ctg_loc = os.path.join("cellranger.multi.dir", library_id,
                                   "outs/multi/",
                                   vdj_type,
                                   "all_contig_annotations.csv")

            out_loc = os.path.join("cellranger.multi.dir/out.dir/",
                                   library_id,
                                   "unfiltered",
                                   vdj_type,
                                   "all_contig_annotations.csv.gz")

            cellranger.contig_annotations(ctg_loc, out_loc, library_id)


            per_sample_loc = os.path.join("cellranger.multi.dir",
                                          library_id,
                                          "outs/per_sample_outs/")

            per_sample_dirs = glob.glob(per_sample_loc + "*")

            for per_sample_dir in per_sample_dirs:

                sample_id = os.path.basename(per_sample_dir)

                ctg_loc = os.path.join(per_sample_dir,
                                       vdj_type,
                                       "filtered_contig_annotations.csv")

                out_loc = os.path.join("cellranger.multi.dir/out.dir/",
                                       library_id,
                                       "filtered",
                                       sample_id,
                                       vdj_type,
                                       "filtered_contig_annotations.csv.gz")

                cellranger.contig_annotations(ctg_loc, out_loc, library_id)

    IOTools.touch_file(outfile)



@transform(postProcessVDJ,
           regex(r"(.*)/out.dir/(.*)/post.process.vdj.sentinel"),
           r"\1/out.dir/\2/register.vdj.sentinel")
def vdjAPI(infile, outfile):
    '''
    Register the post-processed VDJ contigfiles on the API endpoint
    '''

    x = T.api("cellranger.multi")

    vdj_template = {"contig_annotations": {"path":"path/to/annotations.csv.gz",
                                           "format": "csv",
                                           "description": "per-cell contig annotations"}}

    library_id = outfile.split("/")[-2]

    source_loc = os.path.dirname(infile)

    for data_subset in ["unfiltered", "filtered"]:

        for vdj_type in ["vdj_b", "vdj_t"]:


            if data_subset == "filtered":
                data_subset_path = data_subset + "/" + library_id
                prefix = "filtered"
            elif data_subset == "unfiltered":
                data_subset_path = data_subset
                prefix = "all"
            else:
                raise ValueError("subset not recognised")

            vdj_loc = os.path.join(source_loc,
                                   data_subset_path,
                                   vdj_type)

            if os.path.exists(vdj_loc):

                contig_file = os.path.join(vdj_loc,
                                           prefix + "_contig_annotations.csv.gz")

                vdj_x = vdj_template.copy()
                vdj_x["contig_annotations"]["path"] = contig_file

                x.define_dataset(analysis_name=vdj_type,
                          data_subset=data_subset,
                          data_id=library_id,
                          file_set=vdj_x,
                          analysis_description="cellranger contig annotations")

                x.register_dataset()

#
# ---------------------------------------------------
# Generic pipeline tasks

@follows(cellrangerMulti, 
         mtxAPI, h5API, vdjAPI)
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
        os.symlink("cellranger.multi/counts", "api/counts")


def main(argv=None):
    if argv is None:
        argv = sys.argv
    P.main(argv)

if __name__ == "__main__":
    sys.exit(P.main(sys.argv))
