##############################################################################
#
#   Kennedy Institute of Rheumatology
#
#   $Id$
#
#   Copyright (C) 2018 Stephen Sansom
#
#   This program is free software; you can redistribute it and/or
#   modify it under the terms of the GNU General Public License
#   as published by the Free Software Foundation; either version 2
#   of the License, or (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program; if not, write to the Free Software
#   Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
###############################################################################

"""===========================
Pipeline Integration
===========================

:Author: Kathrin Jansen
:Release: $Id$
:Date: |today|
:Tags: Python

Overview
========

This pipeline combines different integration methods, mainly using Satija lab's
Seurat package (http://satijalab.org/seurat/).

For key parameters a range of choices can be specified. The pipeline will
generate one report for each sample or experiment. All integration tasks and
parameter combinations will be run in parallel on an HPC cluster.

The pipeline also assesses the integration by using metrics from the Seurat
paper, the iLISI (harmony), the k-bet package and (optional) a similar entropy metric
to what is suggested in the conos alignment method.

Usage
=====

See :ref:`PipelineSettingUp` and :ref:`PipelineRunning` on general
information how to use CGAT pipelines.

Configuration
-------------

The pipeline requires a configured :file:`pipeline.yml` file.

Default configuration files can be generated by executing:

python <dropdir>/pipeline_integration.py config


Input files
-----------

The pipeline takes as input a file named input_samples.tsv. This
file has to contain a column named sample_id representing the
name for a sample or aggregated experiment. The other required
column is 'path'. This has to be the path to the directory
containing the aggregated matrix, metadata, barcode and features
file for the respective sample (e.g. dropflow qc output)

sample_id  path
pbmc       /path/to/matrix/

$ ls /path/to/matrix/
barcodes.tsv.gz  features.tsv.gz  matrix.mtx.gz  metadata.tsv.gz


Dependencies
------------

This pipeline requires:

* cgat-core: https://github.com/cgat-developers/cgat-core
* R & various packages.


Pipeline output
===============

For each sample and each combination of parameters the following is
generated within a folder for each tool+parameter:

* UMAP colored by the metadata column used for integration
* output of kbet, Seurats integration methods and harmony's iLISI in
folder assess.integration.dir
* folder summary.plots.dir with summaries of each metric above
* folder summary.plots.dir also contains a csv file with the metrics
* (optional) within each folder with different cluster resolutions, a folder with
entropy plots and UMAP with cluster assignments


"""

from ruffus import *
from pathlib import Path
import sys
import os
import shutil
import glob
import sqlite3
import yaml
import numpy as np
import pandas as pd
from shutil import copyfile
from scipy.stats.mstats import gmean
import cgatcore.experiment as E
from cgatcore import pipeline as P
import cgatcore.iotools as IOTools

# -------------------------- < parse parameters > --------------------------- #

# load options from the config file
PARAMS = P.get_parameters(
    ["%s/pipeline.yml" % os.path.splitext(__file__)[0],
     "../pipeline.yml",
     "pipeline.yml"])

# set the location of the tenx code directory
if "code_dir" not in PARAMS.keys():
    PARAMS["code_dir"] = Path(__file__).parents[1]
else:
    raise ValueError("Could not set the location of the code directory")


# ----------------------- < pipeline configuration > ------------------------ #

# handle pipeline configuration
if len(sys.argv) > 1:
        if(sys.argv[1] == "config") and __name__ == "__main__":
                    sys.exit(P.main(sys.argv))


# ########################################################################### #
# ###### check file with input samples and location of aggr matrix ########## #
# ########################################################################### #

@originate("input.check.sentinel")
def checkInputs(outfile):
    '''Check that input_samples.tsv exists and the path given in the file
       exists. Then make one folder for each sample/experiments called
       *.exp.dir '''

    if not os.path.exists("input_samples.tsv"):
        raise ValueError('File specifying the input samples is not present.'
                         'The file needs to be named "input_samples.tsv" ')

    samples = pd.read_csv("input_samples.tsv", sep='\t')
    for p in samples["path"]:
        if not os.path.exists(p):
            raise ValueError('Aggregated, filtered matrix input folder'
                             ' does not exist.')

    IOTools.touch_file(outfile)



# ########################################################################### #
# ############## Per-parameter combination analysis runs #################### #
# ########################################################################### #

# For each sample, one run will be performed for each combination
# of the integration parametes defined for each individual tool

def genClusterJobs():
    '''
    Generate cluster jobs with all paramter combinations.
    '''

    samples = pd.read_csv("input_samples.tsv", sep='\t')

    for sample in samples["sample_id"]:
        outdir = sample + ".exp.dir"
        if not os.path.exists(outdir):
            os.makedirs(outdir)

    # process all the integration experiments
    experiments = [s + ".exp.dir" for s in samples["sample_id"]]

    for dirname in experiments:
        infile = None
        outf = "prep_folder.sentinel"

        # which alignment tools to run
        tools_str = str(PARAMS["integration_tools_run"])
        tools = tools_str.strip().replace(" ", "").split(",")

        # make per-batch merge option
        mergedhvg_str = str(PARAMS["hvg_merged"])
        mergedhvg = mergedhvg_str.strip().replace(" ", "").split(",")
        for (i, item) in enumerate(mergedhvg):
            if item == '0':
                mergedhvg[i] = "perbatch"
            elif item == '1':
                mergedhvg[i] = "merged"
            else:
                raise ValueError("Merge setting for hvg can only be 0 or 1.")

        ngenes_str = str(PARAMS["hvg_ngenes"])
        ngenes = ngenes_str.strip().replace(" ", "").split(",")
        pc_str = str(PARAMS["integration_number_pcs"])
        pcs = pc_str.strip().replace(" ", "").split(",")
        # make jobs for non-integrated sample
        for n in ngenes:
            for m in mergedhvg:
                for p in pcs:
                    outfile = os.path.join(dirname, "rawdata.integrated.dir",
                                           "_".join([n,m,p]) +".run.dir", outf)
                    yield [infile, outfile]

        for tool in tools:

            if 'harmony' in tool:
                k_str = str(PARAMS["harmony_sigma"])
                ks = k_str.strip().replace(" ", "").split(",")
                for n in ngenes:
                    for p in pcs:
                        for k in ks:
                            for m in mergedhvg:
                                outname = "_".join([n,m,p,k]) + ".run.dir"
                                outfile = os.path.join(dirname, "harmony.integrated.dir",
                                                       outname, outf)
                                yield [infile, outfile]

            if 'bbknn' in tool:
                for n in ngenes:
                    for p in pcs:
                        for m in mergedhvg:
                            outname = "_".join([n,m,p]) + ".run.dir"
                            outfile = os.path.join(dirname, "bbknn.integrated.dir",
                                                   outname, outf)
                            yield [infile, outfile]

            if 'scanorama' in tool:
                for n in ngenes:
                    for p in pcs:
                        for m in mergedhvg:
                            outname = "_".join([n,m,p]) + ".run.dir"
                            outfile = os.path.join(dirname, "scanorama.integrated.dir",
                                                   outname, outf)
                            yield [infile, outfile]


@files(genClusterJobs)
def prepFolders(infile, outfile):
    '''Task to prepare folders for integration'''

    # create the output directories
    outdir = os.path.dirname(outfile)
    if not os.path.exists(outdir):
        os.makedirs(outdir)

    IOTools.touch_file(outfile)


# ########################################################################### #
# #################### Scanpy-based integration ############################# #
# ########################################################################### #

@transform(prepFolders,
           regex(r"(.*).exp.dir/(.*).integrated.dir/(.*).run.dir/prep_folder.sentinel"),
           r"\1.exp.dir/\2.integrated.dir/\3.run.dir/scanpy.dir/integration_python.sentinel")
def runScanpyIntegration(infile, outfile):
    '''Run scanpy normalization, hv genes and harmonypy on the data'''

    outdir = os.path.dirname(outfile)
    # make scanpy.dir for output files
    if not os.path.exists(outdir):
        os.makedirs(outdir)

    tool = outfile.split("/")[1].split(".")[0]
    run_options = outfile.split("/")[2][:-len(".run.dir")]
    log_file = outfile.replace(".sentinel", ".log")

    options = {}
    # add task specific options
    options["code_dir"] = os.fspath(PARAMS["code_dir"])
    options["outdir"] = outdir

    # extract path from input_samples.tsv
    sample_name = outfile.split("/")[0][:-len(".exp.dir")]
    samples = pd.read_csv("input_samples.tsv", sep='\t')
    samples.set_index("sample_id", inplace=True)
    infolder = samples.loc[sample_name, "path"]

    options["matrixdir"] = infolder
    options["tool"] = tool
    options["split_var"] = PARAMS["integration_split_factor"]
    options["ngenes"] = int(run_options.split("_")[0])
    options["merge_hvg"] = run_options.split("_")[1]

    options["regress_latentvars"] = str(PARAMS["regress_latentvars"])
    options["regress_cellcycle"] = str(PARAMS["regress_cellcycle"])

    # add metadata options
    options["metadata_file"] = PARAMS["metadata_path"]
    options["metadata_id"] = PARAMS["metadata_id_col"]

    if (os.path.isfile(PARAMS["cellcycle_sgenes"]) and
        os.path.isfile(PARAMS["cellcycle_g2mgenes"]) ):
        options["sgenes"] = PARAMS["cellcycle_sgenes"]
        options["g2mgenes"] = PARAMS["cellcycle_g2mgenes"]


    # add path to the list of hv genes to exclude from hv genes
    if os.path.isfile(PARAMS["hvg_exclude"]):
        options["hvg_exclude"] = PARAMS["hvg_exclude"]

    # add path to the list of hv genes to use for integration
    if os.path.isfile(PARAMS["hvg_list"]):
        options["hv_genes"] = PARAMS["hvg_list"]

    options["nPCs"] = int(run_options.split("_")[2])
    options["totalPCs"] = int(PARAMS["integration_total_number_pcs"])
    if tool == 'harmony':
        ## TO DO: add theta and lambda as options
        sigma = run_options.split("_")[3]
        options["sigma"] = float(sigma)

    # resource allocation
    nslots = PARAMS["resources_integration_slots"]
    job_threads = nslots

    if ("G" in PARAMS["resources_job_memory_high"] or
    "M" in PARAMS["resources_job_memory_high"] ):
        job_memory = PARAMS["resources_job_memory_high"]

    # save the parameters
    task_yaml_file = os.path.abspath(os.path.join(outdir, "integration_python.yml"))
    with open(task_yaml_file, 'w') as yaml_file:
        yaml.dump(options, yaml_file)


    statement = ''' python %(code_dir)s/python/run_scanpy_integration.py
                    --task-yml=%(task_yaml_file)s &> %(log_file)s
                '''
    P.run(statement)
    IOTools.touch_file(outfile)

# ########################################################################### #
# ############## Calculate UMAP for visualisation ########################### #
# ########################################################################### #

@transform(runScanpyIntegration,
           regex(r"(.*).exp.dir/(.*).integrated.dir/(.*).run.dir/scanpy.dir/integration_python.sentinel"),
           r"\1.exp.dir/\2.integrated.dir/\3.run.dir/scanpy.dir/plots_umap_scanpy.sentinel")
def runScanpyUMAP(infile, outfile):
    '''Run scanpy UMAP and make plots'''

    indir = os.path.dirname(infile)
    outdir = os.path.dirname(outfile)
    sampleDir = "/".join(indir.split("/")[:-2])
    tool = sampleDir.split("/")[1].split(".")[0]

    plot_vars_str = str(PARAMS["qc_integration_plot"])
    if plot_vars_str == 'none':
        plot_vars = str(PARAMS["integration_split_factor"])
    else:
        plot_vars = plot_vars_str.strip().replace(" ", "").split(",")
        plot_vars = ",".join(plot_vars + [str(PARAMS["integration_split_factor"])])

    options = {}
    options["code_dir"] = os.fspath(PARAMS["code_dir"])
    # this dir also contains the normalized_integrated_anndata.h5ad file
    options["outdir"] = outdir
    options["plot_vars"] = plot_vars
    options["tool"] = tool
    # info to remove metadata columns
    options["metadata_file"] = PARAMS["metadata_path"]

    log_file = outfile.replace(".sentinel", ".log")

    # resource allocation
    nslots = PARAMS["resources_nslots"]
    job_threads = nslots

    if ("G" in PARAMS["resources_job_memory_standard"] or
    "M" in PARAMS["resources_job_memory_standard"] ):
        job_memory = PARAMS["resources_job_memory_standard"]

    # save the parameters
    task_yaml_file = os.path.abspath(os.path.join(outdir, "plots_umap_scanpy.yml"))
    with open(task_yaml_file, 'w') as yaml_file:
        yaml.dump(options, yaml_file)


    statement = ''' python %(code_dir)s/python/plot_umap_scanpy.py
                    --task-yml=%(task_yaml_file)s &> %(log_file)s
                '''
    P.run(statement)
    IOTools.touch_file(outfile)


@transform(runScanpyUMAP,
           regex(r"(.*).exp.dir/(.*).integrated.dir/(.*).run.dir/scanpy.dir/plots_umap_scanpy.sentinel"),
           r"\1.exp.dir/\2.integrated.dir/\3.run.dir/scanpy.dir/R_plots.dir/plots_umap.sentinel")
def plotUMAP(infile, outfile):
    '''
    Plot UMAP with different variables
    '''
    indir = os.path.dirname(infile)
    outdir = os.path.dirname(outfile)
    if not os.path.exists(outdir):
        os.makedirs(outdir)

    plot_vars_str = str(PARAMS["qc_integration_plot"])
    if plot_vars_str == 'none':
        plot_vars = str(PARAMS["integration_split_factor"])
    else:
        plot_vars = plot_vars_str.strip().replace(" ", "").split(",")
        plot_vars = ",".join(plot_vars + [str(PARAMS["integration_split_factor"])])

    sampleDir = "/".join(indir.split("/")[:-1])
    #tool = sampleDir.split("/")[1].split(".")[0]

    coord_file = os.path.join(indir, "umap.tsv.gz")

    options = {}
    options["code_dir"] = os.fspath(PARAMS["code_dir"])
    options["outdir"] = outdir
    options["coord_file"] = coord_file
    options["plot_vars"] = plot_vars
    #options["integration_tool"] = tool
    options["metadata"] = os.path.join(indir, "metadata.tsv.gz")

    if os.path.isfile(PARAMS["qc_integration_plot_clusters"]):
        options["plot_clusters"] = str(PARAMS["qc_integration_plot_clusters"])

    log_file = outfile.replace("sentinel","log")

    task_yaml_file = os.path.abspath(os.path.join(outdir, "plot_umap.yml"))
    with open(task_yaml_file, 'w') as yaml_file:
        yaml.dump(options, yaml_file)

    job_threads = PARAMS["resources_nslots"]
    if ("G" in PARAMS["resources_job_memory_standard"] or
    "M" in PARAMS["resources_job_memory_standard"] ):
        job_memory = PARAMS["resources_job_memory_standard"]

    statement = '''Rscript %(code_dir)s/R/integration_plot_umap.R
                   --task_yml=%(task_yaml_file)s
                   --log_filename=%(log_file)s
                '''
    P.run(statement)
    IOTools.touch_file(outfile)


# ########################################################################### #
# ####### Make summary pdf with methods and selected variables ############## #
# ########################################################################### #

def genJobsSummary():
    '''Job generator for summary jobs '''
    infile = None
    dirs = os.listdir()
    exp_dirs = [d for d in dirs if '.exp.dir' in d]
    for d in exp_dirs:
        outfile = os.path.join(d, "summary.dir", "make_summary.sentinel")
        yield(infile, outfile)


@active_if(PARAMS["report_umap_run"])
@follows(plotUMAP)
@files(genJobsSummary)
def summariseUMAP(infile, outfile):
    '''
    Summarise UMAP from different methods
    '''
    outdir = os.path.dirname(outfile)
    if not os.path.exists(outdir):
        os.makedirs(outdir)


    indir = outfile.split("/")[0]
    ## make plots for different combinations of variables
    summaries = [k.split("_")[-1] for k in PARAMS.keys()
               if k.startswith("report_umap_summary_")]

    tools_str = str(PARAMS["integration_tools_run"])
    tools = tools_str.strip().replace(" ", "").split(",")
    tools = tools + ['rawdata']

    # read selected parameters for the summary pages
    ngenes = str(PARAMS["report_umap_ngenes"])
    sigma = str(PARAMS["report_umap_sigma"])
    merged_hvg = PARAMS["report_umap_merged_hvg"]
    number_pcs = str(PARAMS["report_umap_number_pcs"])

    if merged_hvg == '0':
        mergedhvg = "perbatch"
    else:
        mergedhvg = "merged"

    # get all required tool folders
    rawdatadir,harmonydir,bbknndir,scanoramadir=0,0,0,0
    for t in tools:
        tooldir = os.path.join(indir, t + ".integrated.dir")
        run_folders = [o for o in os.listdir(tooldir)
                       if os.path.isdir(os.path.join(tooldir,o))]
        if t == "harmony":
            rundir = "_".join([ngenes,mergedhvg,number_pcs,sigma]) + ".run.dir"
        else:
            rundir = "_".join([ngenes,mergedhvg,number_pcs]) + ".run.dir"

        if not rundir in run_folders:
            raise ValueError("Folder with this setting is not present, "
                             "adjust settings in yml")

        if t == 'harmony':
            harmonydir = os.path.join(tooldir, rundir, "scanpy.dir", "R_plots.dir")
        elif t == 'rawdata':
            rawdir = os.path.join(tooldir, rundir, "scanpy.dir", "R_plots.dir")
        elif t == 'bbknn':
            bbknndir = os.path.join(tooldir, rundir, "scanpy.dir", "R_plots.dir")
        elif t == 'scanorama':
            scanoramadir = os.path.join(tooldir, rundir, "scanpy.dir", "R_plots.dir")

    #statements = []

    # Run once for each summary page
    for s in summaries:
        print(s)
        vars_file = os.path.join(outdir, str(s)+".dir", "latexVars.sty")
        summary_dir = os.path.join(outdir, str(s) + ".dir")
        if not os.path.exists(summary_dir):
            os.makedirs(summary_dir)
        vars_use = PARAMS["report_umap_summary_" + s]
        vars_plot = [x.strip() for x in
                         vars_use.split(",")]
        vars_plot = [x.replace("_", "-") if '_' in x else x for x in vars_plot]
        print(vars_plot)
        varone,vartwo,varthree,varfour = vars_plot

        vars = {"rundir": "%(rundir)s" % locals(),
                "integrationVar": "%(integration_split_factor)s" % PARAMS,
                "varone": "%(varone)s" % locals(),
                "vartwo": "%(vartwo)s" % locals(),
                "varthree": "%(varthree)s" % locals(),
                "varfour": "%(varfour)s" % locals(),
                "rawdir": "%(rawdir)s" %locals()}

        if 'harmony' in tools:
            vars['harmonydir'] = harmonydir
        if 'bbknn' in tools:
            vars['bbknndir'] = bbknndir
        if 'scanorama' in tools:
            vars['scanoramadir'] = scanoramadir


        # write file with all variable for this summary
        with open(vars_file, "w") as ofh:
            for command, value in vars.items():
                ofh.write("\\newcommand{\\" + command + "}{" + value + "}\n")

        # make a tex file
        compilation_dir = os.path.join(summary_dir, ".latex_compilation.dir")
        if not os.path.exists(compilation_dir):
            os.makedirs(compilation_dir)

        jobName = s + "_summary"

        statement = '''pdflatex -output-directory=%(compilation_dir)s
                            -jobname=%(jobName)s
                       '\\input %(vars_file)s '''

        statement += '''
                     \\input %(code_dir)s/scpipelines/pipeline_integration/tex/begin.tex
                     '''
        statement += '''
                     \\input %(code_dir)s/scpipelines/pipeline_integration/tex/col_rawdata.tex
                     '''

        if 'harmony' in tools:
            statement += '''
                     \\input %(code_dir)s/scpipelines/pipeline_integration/tex/col_harmony.tex
                     '''
        if 'bbknn' in tools:
            statement += '''
                     \\input %(code_dir)s/scpipelines/pipeline_integration/tex/col_bbknn.tex
                     '''
        if 'scanorama' in tools:
            statement += '''
                     \\input %(code_dir)s/scpipelines/pipeline_integration/tex/col_scanorama.tex
                     '''
        statement += '''
                     \\input %(code_dir)s/scpipelines/pipeline_integration/tex/col_legend.tex'
                     '''


        # Deliberately run twice - necessary for LaTeX compilation..
        P.run(statement)
        P.run(statement)

        # Move the compiled pdfs to report.dir
        shutil.move(os.path.join(compilation_dir, jobName + ".pdf"),
                    os.path.join(summary_dir, jobName+".pdf"))
    IOTools.touch_file(outfile)


@follows(runScanpyUMAP)
@transform(runScanpyIntegration,
           regex(r"(.*).exp.dir/(.*).integrated.dir/(.*).run.dir/scanpy.dir/integration_python.sentinel"),
           r"\1.exp.dir/\2.integrated.dir/\3.run.dir/scanpy.dir/assess_integration.dir/run_ilisi.sentinel")

def runLISIpy(infile, outfile):
    '''Assess the integration using iLISI (lisi on batch/dataset).
       Use the python implementation as part of the harmonypy package
    '''
    outdir = os.path.dirname(outfile)
    if not os.path.exists(outdir):
        os.makedirs(outdir)

    # extract tool from file name
    tool = outfile.split("/")[1].split(".")[0]
    log_file = outfile.replace(".sentinel", ".log")

    options = {}
    options["split_var"] = PARAMS["integration_split_factor"]
    options["code_dir"] = os.fspath(PARAMS["code_dir"])
    options["outdir"] = outdir

    if tool == "harmony":
        file_name = "harmony.tsv.gz"
    elif tool == "scanorama":
        file_name = "scanorama.tsv.gz"
    elif tool == "bbknn":
        ## this is not ideal but correction happens
        ## post PCA.
        file_name = "umap.tsv.gz"
    else:
        file_name = "pca.tsv.gz"

    options["comp_file"] = os.path.join(os.path.dirname(infile),
                                        file_name)

    job_threads = PARAMS["resources_nslots"]
    if ("G" in PARAMS["resources_job_memory_standard"] or
    "M" in PARAMS["resources_job_memory_standard"] ):
        job_memory = PARAMS["resources_job_memory_standard"]

    task_yaml_file = os.path.abspath(os.path.join(outdir, "run_ilisi.yml"))
    with open(task_yaml_file, 'w') as yaml_file:
        yaml.dump(options, yaml_file)

    statement = ''' python %(code_dir)s/python/run_lisi.py
                    --task-yml=%(task_yaml_file)s &> %(log_file)s
                '''

    P.run(statement)
    IOTools.touch_file(outfile)


# ########################################################################### #
# ##################### full target: to run all tasks ####################### #
# ########################################################################### #

@follows(runScanpyUMAP, plotUMAP, runLISIpy, summariseUMAP)
def full():
    pass


pipeline_printout_graph ( "pipeline_flowchart.svg",
                          "svg",
                          [full],
                          no_key_legend=True)
pipeline_printout_graph ( "pipeline_flowchart.png",
                          "png",
                          [full],
                          no_key_legend=True)

# ------------------- < ***** end of pipeline **** > ------------------------ #

if __name__ == "__main__":
    sys.exit(P.main(sys.argv))
