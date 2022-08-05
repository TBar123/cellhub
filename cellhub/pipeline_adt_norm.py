'''
==========================
Pipeline ADT normalization
==========================

Overview
========
This pipeline implements three normalization methods:

* DSB (https://www.biorxiv.org/content/10.1101/2020.02.24.963603v3)

* Median-based (https://bioconductor.org/books/release/OSCA/integrating-with-protein-abundance.html)

* CLR (https://satijalab.org/seurat/archive/v3.0/multimodal_vignette.html)

Configuration
-------------
The pipeline requires a configured :file:`pipeline_adt_norm.yml` file. Default configuration files can be generated by executing: ::

   python <srcdir>/pipeline_adt_norm.py config


Input files
-----------

This pipeline requires the unfiltered gene-expression and ADT count matrices 
and a list of high quality barcodes most likely representing single-cells.

This means that ideally this pipeline is run after high quality cells are selected
via the pipeline_fetch_cells.py. 

This pipeline will look for the unfiltered matrix in the api:
  
  ./api/cellranger.multi/ADT/unfiltered/*/mtx/*.gz

  ./api/cellranger.multi/GEX/unfiltered/*/mtx/*.gz 

Dependencies
------------
This pipeline requires:
* cgat-core: https://github.com/cgat-developers/cgat-core
* R dependencies required in the r scripts


Pipeline output
===============
The pipeline returns a adt_norm.dir folder containing one folder per methodology
adt_dsb.dir, adt_median.dir, and adt_clr.dir with per-sample folders 
conatining market matrices [features, qc-barcodes] with the normalized values. 

Code
====

'''


from ruffus import *
from ruffus.combinatorics import *
import sys
import os
from cgatcore import pipeline as P
import cgatcore.iotools as IOTools
from pathlib import Path
import pandas as pd
import glob

import cellhub.tasks.control as C
import cellhub.tasks.api as api

# Override function to collect config files
P.control.write_config_files = C.write_config_files


# -------------------------- < parse parameters > --------------------------- #

# load options from the yml file
parameter_file = C.get_parameter_file(__file__, __name__)
PARAMS = P.get_parameters(parameter_file)

# Set the location of the cellhub code directory
if "code_dir" not in PARAMS.keys():
    PARAMS["code_dir"] = Path(__file__).parents[1]
else:
    if PARAMS["code_dir"] != Path(__file__).parents[1]:
        raise ValueError("Could not set the location of "
                         "the pipeline code directory")
print(PARAMS)

# ----------------------- < pipeline configuration > ------------------------ #

# handle pipeline configuration
if len(sys.argv) > 1:
        if(sys.argv[1] == "config") and __name__ == "__main__":
                    sys.exit(P.main(sys.argv))


# ############################################################################ #
# #################### Calculate seq depth distributions  #################### #
# ############################################################################ #

@follows(mkdir("adt_norm.dir"))
@transform(glob.glob("api/cellranger.multi/GEX/unfiltered/*/mtx/matrix.mtx.gz"),
           regex(r".*/.*/.*/.*/(.*)/mtx/matrix.mtx.gz"),
           r"adt_norm.dir/adt_dsb.dir/\1/\1_gex.sentinel")
def gexdepth(infile, outfile):
    '''
    This task will run R/adt_calculate_depth_dist.R,
    It will describe the GEX UMI distribution of the background and cell-containing 
    barcodes. This will help to assess the quality of the ADT data and will inform
    about the definition of the background barcodes.
    '''

    outdir = os.path.dirname(outfile)
    if not os.path.exists(outdir):
        parentdir = os.path.dirname(outdir)
        if not os.path.exists(parentdir):
          os.mkdir(parentdir)
          os.mkdir(outdir)

    # Get cellranger directory and id
    library_name = os.path.basename(outfile)[:-len(".sentinel")]
    unfiltered_dir = os.path.dirname(infile)
    filtered_dir = unfiltered_dir.replace("unfiltered", "filtered")

    # Other settings
    job_threads = PARAMS["resources_threads"]
    if ("G" in PARAMS["resources_job_memory"] or
        "M" in PARAMS["resources_job_memory"] ):
        job_memory = PARAMS["resources_job_memory"]
        
    # High qualiity cell-barcodes
    qc_barcode = PARAMS["qc_barcode"]

    log_file = outfile.replace(".sentinel", ".log")

    out_file = outfile.replace(".sentinel", ".tsv.gz")

    # Formulate and run statement
    statement = '''Rscript %(code_dir)s/R/scripts/adt_calculate_depth_dist.R
                 --unfiltered_dir=%(unfiltered_dir)s
                 --filtered_dir=%(filtered_dir)s
                 --qc_bar=%(qc_barcode)s
                 --library_id=%(library_name)s
                 --numcores=%(job_threads)s
                 --log_filename=%(log_file)s
                 --outfile=%(out_file)s
              '''
    P.run(statement)

    # Create sentinel file
    IOTools.touch_file(outfile)


@merge(gexdepth,
       "adt_norm.dir/adt_dsb.dir/api_gex.sentinel")
def gexdepthAPI(infiles, outfile):
    '''
    Add the umi depth metrics results to the API
    '''

    file_set={}

    for lib in infiles:

        tsv_path = lib.replace(".sentinel",".tsv.gz")
        library_id = os.path.basename(tsv_path).replace("_gex", "")

        file_set[library_id] = {"path": tsv_path,
                                "description":"all barcodes gex umi depth table for library " +\
                                library_id,
                                "format":"tsv"}

    x = api.api("adt_norm")

    x.define_dataset(analysis_name="depth_metrics",
              data_subset="gex",
              file_set=file_set,
              analysis_description="per library tables of cell GEX depth")

    x.register_dataset()

    # Create sentinel file
    IOTools.touch_file(outfile)

@follows(mkdir("adt_norm.dir"))
@transform(glob.glob("api/cellranger.multi/ADT/unfiltered/*/mtx/matrix.mtx.gz"),
           regex(r".*/.*/.*/.*/(.*)/mtx/matrix.mtx.gz"),
           r"adt_norm.dir/adt_dsb.dir/\1/\1_adt.sentinel")
def adtdepth(infile, outfile):
    '''
    This task will run R/adt_calculate_depth_dist.R,
    It will describe the ADT UMI distribution of the background and cell-containing 
    barcodes. This will help to assess the quality of the ADT data and will inform
    the definition of the background barcodes.
    '''

    outdir = os.path.dirname(outfile)
    if not os.path.exists(outdir):
        parentdir = os.path.dirname(outdir)
        if not os.path.exists(parentdir):
          upparentdir = os.path.dirname(parentdir)
          if not os.path.exists(upparentdir):
            os.mkdir(upparentdir)
            os.mkdir(parentdir)
            os.mkdir(outdir)

    # Get cellranger directory and id
    library_name = os.path.basename(outfile)[:-len(".sentinel")]
    unfiltered_dir = os.path.dirname(infile)
    filtered_dir = unfiltered_dir.replace("unfiltered", "filtered")
    
    # Features to remove
    rm_feat = PARAMS["rm_feat"]
    # High qualiity cell-barcodes
    qc_barcode = PARAMS["qc_barcode"]
    
    # Other settings
    job_threads = PARAMS["resources_threads"]
    if ("G" in PARAMS["resources_job_memory"] or
        "M" in PARAMS["resources_job_memory"] ):
        job_memory = PARAMS["resources_job_memory"]

    log_file = outfile.replace(".sentinel", ".log")

    out_file = outfile.replace(".sentinel", ".tsv.gz")

    # Formulate and run statement
    statement = '''Rscript %(code_dir)s/R/scripts/adt_calculate_depth_dist.R
                 --unfiltered_dir=%(unfiltered_dir)s
                 --filtered_dir=%(filtered_dir)s
                 --rm_feat=%(rm_feat)s
                 --qc_bar=%(qc_barcode)s
                 --library_id=%(library_name)s
                 --numcores=%(job_threads)s
                 --log_filename=%(log_file)s
                 --outfile=%(out_file)s
              '''
    P.run(statement)

    # Create sentinel file
    IOTools.touch_file(outfile)

@merge(adtdepth,
       "adt_norm.dir/adt_dsb.dir/api_adt.sentinel")
def adtdepthAPI(infiles, outfile):
    '''
    Add the umi depth metrics results to the API
    '''

    file_set={}

    for lib in infiles:

        tsv_path = lib.replace(".sentinel",".tsv.gz")
        library_id = os.path.basename(tsv_path).replace("_adt", "")

        file_set[library_id] = {"path": tsv_path,
                                "description":"all barcodes adt umi depth table for library " +\
                                library_id,
                                "format":"tsv"}

    x = api.api("adt_norm")

    x.define_dataset(analysis_name="depth_metrics",
              data_subset="adt",
              file_set=file_set,
              analysis_description="per library tables of cell ADT depth")

    x.register_dataset()

    # Create sentinel file
    IOTools.touch_file(outfile)

@follows(gexdepthAPI)
@transform(adtdepth, 
           regex(r".*/.*/.*/(.*)_adt.sentinel"), 
           r"adt_norm.dir/adt_dsb.dir/\1/\1_plot.sentinel")
def adt_plot_norm(infile, outfile):
    '''
    This task will run R/adt_plot_norm.R,
    It will create a visual report on the cell vs background dataset split and,
    if the user provided GEX and ADT UMI thresholds, those will be included. 
    '''

    outdir = os.path.dirname(outfile)
    if not os.path.exists(outdir):
        parentdir = os.path.dirname(outdir)
        if not os.path.exists(parentdir):
          os.mkdir(parentdir)
          os.mkdir(outdir)

    # Get cellranger directory and id
    library_name = os.path.basename(outfile)[:-len("_plot.sentinel")]
    unfiltered_dir = "api/cellranger.multi/ADT/unfiltered/" + library_name +"/mtx" 

    # Other settings
    job_threads = PARAMS["resources_threads"]
    if ("G" in PARAMS["resources_job_memory"] or
        "M" in PARAMS["resources_job_memory"] ):
        job_memory = PARAMS["resources_job_memory"]

    gex_depth = "api/adt.norm/depth_metrics/gex/" + library_name + "_gex.tsv.gz"
    adt_depth = "api/adt.norm/depth_metrics/adt/" + library_name + "_adt.tsv.gz"
    
    # Features to remove
    rm_feat = PARAMS["rm_feat"]
    # High qualiity cell-barcodes
    qc_barcode = PARAMS["qc_barcode"]
    
    # Background & cell count/features threshold
    bcmin = PARAMS["dsb_background"]["counts"]["min"]
    bcmax = PARAMS["dsb_background"]["counts"]["max"]
    bfmin = PARAMS["dsb_background"]["feats"]["min"]
    bfmax = PARAMS["dsb_background"]["feats"]["max"]
    ccmin = PARAMS["dsb_cell"]["counts"]["min"]
    ccmax = PARAMS["dsb_cell"]["counts"]["max"]
    cfmin = PARAMS["dsb_cell"]["feats"]["min"]
    cfmax = PARAMS["dsb_cell"]["feats"]["max"]

    log_file = outfile.replace(".sentinel", ".log")
    out_file = outfile.replace(".sentinel", ".pdf")

    # Formulate and run statement
    statement = '''Rscript %(code_dir)s/R/scripts/adt_plot_norm.R
                 --unfiltered_dir=%(unfiltered_dir)s
                 --library_id=%(library_name)s
                 --gex_depth=%(gex_depth)s
                 --adt_depth=%(adt_depth)s
                 --rm_feat=%(rm_feat)s
                 --qc_bar=%(qc_barcode)s
                 --bcmin=%(bcmin)s
                 --bcmax=%(bcmax)s
                 --bfmin=%(bfmin)s
                 --bfmax=%(bfmax)s
                 --ccmin=%(ccmin)s
                 --ccmax=%(ccmax)s
                 --cfmin=%(cfmin)s
                 --cfmax=%(cfmax)s
                 --numcores=%(job_threads)s
                 --log_filename=%(log_file)s
                 --outfile=%(out_file)s
              '''
    P.run(statement)

    # Create sentinel file
    IOTools.touch_file(outfile)


# ------------------------------------------------------------------------------
# DSB normalization

@follows(gexdepthAPI)
@transform(gexdepth,
           regex(r".*/.*/.*/(.*)_adt.sentinel"),
           r"adt_norm.dir/adt_dsb.dir/\1/mtx/\1.sentinel")
def dsb_norm(infile, outfile):
    '''
    This task runs R/adt_normalize.R.
    It reads the unfiltered ADT count matrix and calculates DSB normalized ADT 
    expression matrix which is then saved like market matrices per sample.
    '''

    outdir = os.path.dirname(outfile)
    if not os.path.exists(outdir):
        parentdir = os.path.dirname(outdir)
        if not os.path.exists(parentdir):
          os.mkdir(parentdir)
          os.mkdir(outdir)

    # Get cellranger directory and id
    library_name = os.path.basename(outfile)[:-len(".sentinel")]
    unfiltered_dir = "api/cellranger.multi/ADT/unfiltered/" + library_name +"/mtx"
    filtered_dir = unfiltered_dir.replace("unfiltered", "filtered")

    # Other settings
    job_threads = PARAMS["resources_threads"]
    if ("G" in PARAMS["resources_job_memory"] or
        "M" in PARAMS["resources_job_memory"] ):
        job_memory = PARAMS["resources_job_memory"]

    gex_depth = "api/adt.norm/depth_metrics/gex/" + library_name + "_gex.tsv.gz"
    adt_depth = "api/adt.norm/depth_metrics/adt/" + library_name + "_adt.tsv.gz"

    # Features to remove
    rm_feat = PARAMS["rm_feat"]
    # High qualiity cell-barcodes
    qc_barcode = PARAMS["qc_barcode"]
    
    # Background & cell count/features threshold
    bcmin = PARAMS["dsb_background"]["counts"]["min"]
    bcmax = PARAMS["dsb_background"]["counts"]["max"]
    bfmin = PARAMS["dsb_background"]["feats"]["min"]
    bfmax = PARAMS["dsb_background"]["feats"]["max"]
    ccmin = PARAMS["dsb_cell"]["counts"]["min"]
    ccmax = PARAMS["dsb_cell"]["counts"]["max"]
    cfmin = PARAMS["dsb_cell"]["feats"]["min"]
    cfmax = PARAMS["dsb_cell"]["feats"]["max"]

    log_file = outfile.replace(".tsv.gz", ".log")

    out_file = "/".join([os.path.dirname(outfile), "matrix.mtx"])

    # Formulate and run statement
    statement = '''Rscript %(code_dir)s/R/scripts/adt_normalize.R
                 --unfiltered_dir=%(unfiltered_dir)s
                 --filtered_dir=%(filtered_dir)s
                 --library_id=%(library_name)s
                 --gex_depth=%(gex_depth)s
                 --adt_depth=%(adt_depth)s
                 --rm_feat=%(rm_feat)s
                 --qc_bar=%(qc_barcode)s
                 --bcmin=%(bcmin)s
                 --bcmax=%(bcmax)s
                 --bfmin=%(bfmin)s
                 --bfmax=%(bfmax)s
                 --ccmin=%(ccmin)s
                 --ccmax=%(ccmax)s
                 --cfmin=%(cfmin)s
                 --cfmax=%(cfmax)s
                 --numcores=%(job_threads)s
                 --log_filename=%(log_file)s
                 --outfile=%(out_file)s
              '''
    P.run(statement)

    # Create sentinel file
    IOTools.touch_file(outfile)

@transform(dsb_norm,
           regex(r"adt_norm.dir/adt_dsb.dir/.*/mtx/(.*).sentinel"),
           r"adt_norm.dir/adt_dsb.dir/\1/mtx/\1_api_load.sentinel")
def dsbAPI(infile, outfile):
    '''
    Register the ADT normalized mtx files on the API endpoint
    '''
    x = api.api("adt_norm")

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

    library_id = os.path.basename(outfile)[:-len("_api_load.sentinel")]
    mtx_loc = os.path.dirname(infile)

    mtx_x = mtx_template.copy()
    mtx_x["barcodes"]["path"] = os.path.join(mtx_loc, "barcodes.tsv.gz")
    mtx_x["features"]["path"] = os.path.join(mtx_loc, "features.tsv.gz")
    mtx_x["matrix"]["path"] =  os.path.join(mtx_loc, "matrix.mtx.gz")

    x.define_dataset(analysis_name="dsb_norm",
                     data_subset="mtx",
                     data_id=library_id,
                     data_format="mtx",
                     file_set=mtx_x,
                     analysis_description="ADT dsb normalized mtx matrices.")

    x.register_dataset()
    
    # Create sentinel file
    IOTools.touch_file(outfile)


# ------------------------------------------------------------------------------
# Median-based normalization

@follows(mkdir("adt_norm.dir"))
@transform(glob.glob("api/cellranger.multi/ADT/filtered/*/mtx/matrix.mtx.gz"),
           regex(r".*/.*/.*/(.*)/mtx/matrix.mtx.gz"),
           r"adt_norm.dir/adt_median.dir/\1/mtx/\1.sentinel")
def median_norm(infile, outfile):
    '''This task runs R/adt_get_median_normalization.R,
    It reads the filtered ADT count matrix and performed median-based 
    normalization. Calculates median-based normalized ADT expression matrix and
    writes market matrices per sample.
    '''

    outdir = os.path.dirname(outfile)
    if not os.path.exists(outdir):
        parentdir = os.path.dirname(outdir)
        if not os.path.exists(parentdir):
          upparentdir = os.path.dirname(parentdir)
          if not os.path.exists(upparentdir):
            os.mkdir(upparentdir)
            os.mkdir(parentdir)
            os.mkdir(outdir)

    # Get cellranger directory and id
    library_name = os.path.basename(outfile)[:-len(".sentinel")]
    filtered_adt_dir = os.path.dirname(infile)

    # Other settings
    job_threads = PARAMS["resources_threads"]
    if ("G" in PARAMS["resources_job_memory"] or
        "M" in PARAMS["resources_job_memory"] ):
        job_memory = PARAMS["resources_job_memory"]

    # Top highly variable features
    nfeat = "all"
    # Features to remove
    rm_feat = PARAMS["rm_feat"]
    # High qualiity cell-barcodes
    qc_barcode = PARAMS["qc_barcode"]

    log_file = outfile.replace(".sentinel", ".log")

    out_file = "/".join([os.path.dirname(outfile), "matrix.mtx"])

    # Formulate and run statement
    statement = '''Rscript %(code_dir)s/R/scripts/adt_get_median_normalization.R
                 --adt=%(filtered_adt_dir)s
                 --nfeat=%(nfeat)s
                 --rm_feat=%(rm_feat)s
                 --qc_bar=%(qc_barcode)s
                 --numcores=%(job_threads)s
                 --log_filename=%(log_file)s
                 --outfile=%(out_file)s
              '''
    P.run(statement)

    # Create sentinel file
    IOTools.touch_file(outfile)

@transform(median_norm,
           regex(r"adt_norm.dir/adt_median.dir/.*/mtx/(.*).sentinel"),
           r"adt_norm.dir/adt_median.dir/\1/mtx/\1_api_load.sentinel")
def medianAPI(infile, outfile):
    '''
    Register the ADT normalized mtx files on the API endpoint
    '''
    x = api.api("adt_norm")

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

    library_id = os.path.basename(outfile)[:-len("_api_load.sentinel")]
    mtx_loc = os.path.dirname(infile)

    mtx_x = mtx_template.copy()
    mtx_x["barcodes"]["path"] = os.path.join(mtx_loc, "barcodes.tsv.gz")
    mtx_x["features"]["path"] = os.path.join(mtx_loc, "features.tsv.gz")
    mtx_x["matrix"]["path"] =  os.path.join(mtx_loc, "matrix.mtx.gz")

    x.define_dataset(analysis_name="median_norm",
                     data_subset="mtx",
                     data_id=library_id,
                     data_format="mtx",
                     file_set=mtx_x,
                     analysis_description="ADT median-based normalized mtx matrices.")

    x.register_dataset()
    
    # Create sentinel file
    IOTools.touch_file(outfile)

# ------------------------------------------------------------------------------
# CLR normalization

@follows(mkdir("adt_norm.dir"))
@transform(glob.glob("api/cellranger.multi/ADT/filtered/*/mtx/matrix.mtx.gz"),
           regex(r".*/.*/.*/.*/(.*)/mtx/matrix.mtx.gz"),
           r"adt_norm.dir/adt_clr.dir/\1/mtx/\1.sentinel")
def clr_norm(infile, outfile):
    '''This task runs R/get_median_clr_normalization.R,
    It reads the filtered ADT count matrix and performes CLR 
    normalization. Writes market matrices per sample.
    '''

    outdir = os.path.dirname(outfile)
    if not os.path.exists(outdir):
        parentdir = os.path.dirname(outdir)
        if not os.path.exists(parentdir):
          upparentdir = os.path.dirname(parentdir)
          if not os.path.exists(upparentdir):
            os.mkdir(upparentdir)
            os.mkdir(parentdir)
            os.mkdir(outdir)

    # Get cellranger directory and id
    library_name = os.path.basename(outfile)[:-len(".sentinel")]
    filtered_adt_dir = os.path.dirname(infile)

    # Other settings
    job_threads = PARAMS["resources_threads"]
    if ("G" in PARAMS["resources_job_memory"] or
        "M" in PARAMS["resources_job_memory"] ):
        job_memory = PARAMS["resources_job_memory"]

    # Top highly variable features
    nfeat = "all"
    # Features to remove
    rm_feat = PARAMS["rm_feat"]
    # High qualiity cell-barcodes
    qc_barcode = PARAMS["qc_barcode"]

    log_file = outfile.replace(".sentinel", ".log")

    out_file = "/".join([os.path.dirname(outfile), "matrix.mtx"])

    # Formulate and run statement
    statement = '''Rscript %(code_dir)s/R/scripts/adt_get_clr_normalization.R
                 --adt=%(filtered_adt_dir)s
                 --nfeat=%(nfeat)s
                 --rm_feat=%(rm_feat)s
                 --qc_bar=%(qc_barcode)s
                 --numcores=%(job_threads)s
                 --log_filename=%(log_file)s
                 --outfile=%(out_file)s
              '''
    P.run(statement)

    # Create sentinel file
    IOTools.touch_file(outfile)

@transform(clr_norm,
           regex(r"adt_norm.dir/adt_clr.dir/.*/mtx/(.*).sentinel"),
           r"adt_norm.dir/adt_clr.dir/\1/mtx/\1_api_load.sentinel")
def clrAPI(infile, outfile):
    '''
    Register the CLR-normalized ADT mtx files on the API endpoint
    '''
    x = api.api("adt_norm")

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

    library_id = os.path.basename(outfile)[:-len("_api_load.sentinel")]
    mtx_loc = os.path.dirname(infile)

    mtx_x = mtx_template.copy()
    mtx_x["barcodes"]["path"] = os.path.join(mtx_loc, "barcodes.tsv.gz")
    mtx_x["features"]["path"] = os.path.join(mtx_loc, "features.tsv.gz")
    mtx_x["matrix"]["path"] =  os.path.join(mtx_loc, "matrix.mtx.gz")

    x.define_dataset(analysis_name="clr_norm",
                     data_subset="mtx",
                     data_id=library_id,
                     data_format="mtx",
                     file_set=mtx_x,
                     analysis_description="ADT CLR-normalized mtx matrices.")

    x.register_dataset()
    
    # Create sentinel file
    IOTools.touch_file(outfile)

# ---------------------------------------------------
# Generic pipeline tasks

@follows(mkdir("adt_norm.dir"))
@files(None, "adt_norm.dir/plot.sentinel")
def plot(infile, outfile):
    '''Draw the pipeline flowchart'''

    pipeline_printout_graph ( "adt_norm.dir/pipeline_flowchart.svg",
                          "svg",
                          [full],
                          no_key_legend=True)

    pipeline_printout_graph ( "adt_norm.dir/pipeline_flowchart.png",
                          "png",
                          [full],
                          no_key_legend=True)

    IOTools.touch_file(outfile)


@follows(gexdepthAPI, adtdepthAPI, adt_plot_norm, dsb_norm, dsbAPI, median_norm, 
         medianAPI, clr_norm, clrAPI, plot)
def full():
    '''
    Run the full pipeline.
    '''
    pass


def main(argv=None):
    if argv is None:
        argv = sys.argv
    P.main(argv)


if __name__ == "__main__":
    sys.exit(P.main(sys.argv))
