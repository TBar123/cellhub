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
Pipeline Cellranger
===========================
:Author: Sansom lab
:Release: $Id$
:Date: |today|
:Tags: Python

Overview
========

This pipeline performs the following functions:
* Alignment and quantitation of reads obtained from 10X scRNAseq protocols  
  using the "cellranger count" pipeline. 

Usage
=====
See :doc:`Installation</Installation>` and :doc:`Usage</Usage>` on general
information how to use CGAT pipelines.

Configuration
------------
The pipeline requires a configured :file:`pipeline.yml` file.
Default configuration files can be generated by executing:
   python <srcdir>/pipeline_cellranger.py config

Input files
-----------
The pipeline requires FASTQ files from the "cellranger mkfastq" pipeline.
The pipeline can be run for:

(A) gene-expression (GEX) only or 
(B) GEX + Antibody Capture (ADT) read-outs,

Inputs for these two modalities differ:

(A) If runing for GEX only:

The pipeline expects a file describing each sample to be present
in a "data.dir" subfolder.
The sample file should contain the path(s) to the output(s) of
"cellranger mkfastq" (The directory to the fastq files of each seq run).
If multiple sequencing runs were performed, specify one path per line.
The name of the sample file must follow the a four-part syntax:

"sample_name.ncells.RTbatch.sample"

Where:
1. "sample_name" is a user specified sample name;
2. "ncells" is an integer giving the number of expected cells;
3. "exp_batch" is the Retro-Transcriptase batch (10X chip run)
3. ".sample" is the file suffix expected by the pipeline to recognize
   the input samples to align & quantiify.

e.g.
data.dir
|- data.dir/donor1_butyrate.1000.sample

$ cat data.dir/data.dir/donor1_RA.10000.1.sample
/gfs/work/ssansom/10x/holm_butyrate/cellranger/data.dir/392850_21
/gfs/work/ssansom/10x/holm_butyrate/cellranger/data.dir/397106_21

(B) If runing for GEX and ADT of same 10X channels:

The pipeline expects a file per sample with a name following the three-part
syntax described aboved.
Each file must contain the list of libraries obtained for each sample.
This file should be in a "data.dir" subfolder. It must follow the format 
expected for the --libraries argument of the "cellranger count" pipeline
[https://support.10xgenomics.com/single-cell-gene-expression/software/
pipelines/6.0/using/feature-bc-analysis]:
    
A comma separated file with three columns, 

i)   fastqs : path to the directory containing the output of the "cellranger
     mkfastq" 
ii)  sample : sample name assigned in the bcl2fastq sample sheet. Effectively
     the name of the library/sequencing-run <sample_name>_S0_L001_001.fastq.gz
iii) library_type: Either "Gene Expression" or "Antibody Capture"

e.g.
data.dir
|- data.dir/donor1_RA.5000.1.sample

$ cat data.dir/data.dir/donor1_RA.5000.1.sample
fastqs,sample,library_type
/ ... /data.dir/donor1_RA_seq_run1,donor1_RA_seq_run1,Gene Expression
/ ... /data.dir/donor1_RA_seq_run2,donor1_RA_seq_run2,Gene Expression
/ ... /data.dir/donor1_RA_seq_run3,donor1_RA_seq_run3,Antibody Capture
/ ... /data.dir/donor1_RA_seq_run4,donor1_RA_seq_run4,Antibody Capture

In addition, in this GEX + ADT dual data modality, the pipeline requires a Feature Reference 
comma separated, each line declares one unique Feature Barcode. This file will be passed to 
"cellranger count" with the --feature-ref flag. This file should contain at least six columns:
    id : Unique ID for this feature.
    name : Human-readable name for this feature.
    read : Specifies which RNA sequencing read contains the Feature Barcode sequence. R1 or R2
    pattern : Specifies how to extract the Feature Barcode sequence from the read.
    sequence : Nucleotide barcode sequence associated with this feature. 
    feature_type : "Antibody Capture"

Please visit https://support.10xgenomics.com/single-cell-gene-expression/software/pipelines/6.0/using/feature-bc-analysis
for more in-depth details
Define this file location in the .yml file.


Dependencies
------------
This pipeline requires:
* cgat-core: https://github.com/cgat-developers/cgat-core
* cellranger: https://support.10xgenomics.com/single-cell-gene-expression/


Pipeline output
===============
The pipeline returns:
* the output of cellranger count, a folder <sample_name>-count per sample (i.e. one 10X channel).

Code
====
"""
from ruffus import *
from pathlib import Path
import sys
import os
import glob
import sqlite3
import yaml
import cgatcore.experiment as E
from cgatcore import pipeline as P
import cgatcore.iotools as IOTools
import pandas as pd

# -------------------------- < parse parameters > --------------------------- #

# load options from the config file
PARAMS = P.get_parameters(
    ["%s/pipeline.yml" % os.path.splitext(__file__)[0],
     "../pipeline.yml",
     "pipeline.yml"])

# set the location of the cellhub code directory
if "code_dir" not in PARAMS.keys():
    PARAMS["code_dir"] = Path(__file__).parents[1]
else:
    raise ValueError("Could not set the location of the cellhub code directory")


# ----------------------- < pipeline configuration > ------------------------ #

# handle pipeline configuration
if len(sys.argv) > 1:
        if(sys.argv[1] == "config") and __name__ == "__main__":
                    sys.exit(P.main(sys.argv))

# -------------------- < Check sample files availability > ------------------ #

def checkSampleAvailandName(check_only=True):
    '''Check if input samples available and name format.
    Return available samples with right name format
    '''
    sample_files = glob.glob(os.path.join("data.dir", "*.sample"))

    # Check we have input
    if len(sample_files) == 0:
            raise ValueError("No input files detected, please make sure they" 
                             " are named correctly *.sample and placed in the"
                             " right folder ./data.dir")
    
    samples = []

    # Process file names
    for sample_file in sample_files:
        # We expect 4 '.'-delimited sections to the sample filename:
        # <name_field_titles>.<ncells>.<RTbatch>.sample
        sample_basename = os.path.basename(sample_file)
        sample_name_sections = sample_basename.split(".")
        
        if len(sample_name_sections) != 4:
            raise ValueError(
                "%(sample_basename)s does not have the expected"
                " number of dot-separated sections. Format expected is:"
                " sample_name.ncells.RTbatch.sample, e.g. "
                " donor1_RA_R1.5000.1.sample " % locals())
        

@files(None,
        "data.dir/input.check.sentinel")
def checkSampleFileInputs(infile, outfile):
    '''Check sample input .sample files'''

    checkSampleAvailandName()
    
    IOTools.touch_file(outfile)

# -------------------- < Make sample metadata file > -------------------- #

@follows(checkSampleFileInputs)
@merge("data.dir/*.sample", PARAMS["input_samples"])
def makeSampleTable(sample_files, outfile):
    
    # Build the path to the log file
    log_file = outfile + ".log"

    sample_names = []

    for s in sample_files:
        sample_name = os.path.basename(s)
        sample_names.append(sample_name)

    samples = '///'.join(sample_names)

    job_threads = 2
    job_memory = "2000M"

    statement = '''Rscript %(code_dir)s/R/scripts/cellranger_sampleName2metadatatable.R
                   --outfile=%(outfile)s
                   --samplefiles=%(samples)s
                   &> %(log_file)s
                '''

    P.run(statement)
    IOTools.touch_file(outfile + ".sentinel")

# -------------------- < cellranger count GEX > -------------------- #

@active_if(PARAMS["input_modality"] == "GEX")
@follows(makeSampleTable)
@transform("data.dir/*.sample",
        regex(r".*/([^.]*).*.sample"),
        r"\1-count/cellranger.count.sentinel")

def cellrangerCount(infile, outfile):
    '''
    Execute the cell ranger count pipleline for all samples including
    gene-expression only
    '''

    # set key parameters
    # Reference transcriptome

    transcriptome = PARAMS["cellranger_transcriptome"]

    if transcriptome is None:
        raise ValueError('"cellranger_transcriptome" parameter not set'
                ' in file "pipeline.yml"')

    if not os.path.exists(transcriptome):
        raise ValueError('The specified "cellranger_transcriptome"'
                ' file does not exist')

    # Feature (antibody) reference
    featurereference = PARAMS["input_featurereference"]

    # set the maximum number of jobs for cellranger
    max_jobs = PARAMS["running_maxjobs"]

    # parse the sample name and expected cell number
    library_id, cellnumber, batch, trash = os.path.basename(infile).split(".")

    # build lists of the sample files
    seq_folders = []
    sample_ids = []

    # Parse the list of sequencing runs (i.e., paths) for the sample
    with open(infile, "r") as sample_list:
        for line in sample_list:
            seq_folder_path = line.strip()
            if seq_folder_path != "":
                seq_folders.append(seq_folder_path)
                sample_ids.append(os.path.basename(seq_folder_path))

    input_fastqs = ",".join(seq_folders)
    input_samples = ",".join(sample_ids)

    id_tag = library_id + "-count"
    log_file = id_tag + ".log"

    mempercore = PARAMS["cellranger_mempercore"]
    if mempercore:
        mempercore_stat="--mempercore " + str(mempercore)
    else:
        mempercore_stat = ""

    ## send one job script to slurm queue which arranges cellranger run
    ## hard-coded to ensure enough resources
    libfile = os.path.abspath(infile)
    job_threads = 6
    job_memory = "24000M"
    statement = (
            '''cellranger count
                    --id %(id_tag)s
                    --fastqs %(input_fastqs)s
                    --sample %(input_samples)s
                    --transcriptome %(transcriptome)s
                    --expect-cells %(cellnumber)s
                    --chemistry %(cellranger_chemistry)s
                    --jobmode=%(cellranger_job_template)s
                    --maxjobs=%(max_jobs)s
                    --nopreflight
                    %(mempercore_stat)s
                &> %(log_file)s
            ''')

    P.run(statement)

    IOTools.touch_file(outfile)
 
# -------------------- < cellranger count GEX + ADT > -------------------- #

@active_if(PARAMS["input_modality"] == "GEXADT")
@follows(makeSampleTable)
@transform("data.dir/*.sample",
        regex(r".*/([^.]*).*.sample"),
        r"\1-count/cellranger.count.sentinel")

def cellrangerCountFeat(infile, outfile):
    '''
    Execute the cell ranger count pipleline for all samples that include both
    gene-expression and protein-feature detection
    '''

    # set key parameters
    # Reference transcriptome

    transcriptome = PARAMS["cellranger_transcriptome"]

    if transcriptome is None:
        raise ValueError('"cellranger_transcriptome" parameter not set'
                ' in file "pipeline.yml"')

    if not os.path.exists(transcriptome):
        raise ValueError('The specified "cellranger_transcriptome"'
                ' file does not exist')

    # Feature (antibody) reference
    featurereference = PARAMS["input_featurereference"]

    if featurereference is None:
        raise ValueError('"input_featurereference" parameter not set'
                ' in file "pipeline.yml"')

    if not os.path.exists(featurereference):
        raise ValueError('The specified "cellranger_featurereference"'
                ' file does not exist')

    # set the maximum number of jobs for cellranger
    max_jobs = PARAMS["running_maxjobs"]

    # parse the sample name and expected cell number
    library_id, cellnumber, batch, trash = os.path.basename(infile).split(".")

    id_tag = library_id + "-count"
    log_file = id_tag + ".log"

    ## send one job script to slurm queue which arranges cellranger run
    ## hard-coded to ensure enough resources
    libfile = os.path.abspath(infile)
    job_threads = 6
    job_memory = "24000M"
    statement = (
            '''cellranger count
                    --id %(id_tag)s
                    --libraries %(libfile)s
                    --transcriptome %(transcriptome)s
                    --expect-cells %(cellnumber)s
                    --feature-ref %(featurereference)s
                    --chemistry %(cellranger_chemistry)s
                    --jobmode=slurm
                    --maxjobs=%(max_jobs)s
                    --nopreflight
                &> %(log_file)s
            ''')

    P.run(statement)

    IOTools.touch_file(outfile)
    

# Generic pipeline tasks
# ---------------------------------------------------

@follows(cellrangerCountFeat, cellrangerCount)
def full():
    '''
    Run the full pipeline.
    '''
    pass


pipeline_printout_graph ( "pipeline_flowchart.svg",
                          "svg",
                          [full],
                          no_key_legend=True)

pipeline_printout_graph ( "pipeline_flowchart.png",
                          "png",
                          [full],
                          no_key_legend=True)

if __name__ == "__main__":
    sys.exit(P.main(sys.argv))
