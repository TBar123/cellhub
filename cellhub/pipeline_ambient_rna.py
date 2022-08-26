"""
=======================
pipeline_ambient_rna.py
=======================

Overview
========
This pipeline performs the following steps:
* Analyse the ambient RNA profile in each input (eg. channel's or library's raw cellrange matrices)
* Compare ambient RNA profiles across inputs


Configuration
-------------
The pipeline requires a configured :file:`pipeline.yml` file.
Default configuration files can be generated by executing: ::

    python <srcdir>/pipeline_ambient_rna.py config


Input files
-----------
An tsv file called 'input_libraries.tsv' is required.
This file must have column names as explained below.
Must not include row names.
Add as many rows as iput channels/libraries for analysis.

This file must have the following columns:

* library_id - name used throughout. This could be the channel_pool id eg. A1
* raw_path - path to the raw_matrix folder from cellranger count
* exp_batch - might or might not be useful. If not used, fill with "1"
* channel_id - might or might not be useful. If not used, fill with "1"
* seq_batch - might or might not be useful. If not used, fill with "1"
* (optional) excludelist - path to a file with cell_ids to excludelist

You can add any other columns as required, for example pool_id

Dependencies
------------
This pipeline requires:
* cgat-core: https://github.com/cgat-developers/cgat-core
* R dependencies required in the r scripts

Pipeline output
===============
The pipeline returns:
* per-input html report and tables saved in a 'profile_per_input' folder
* ambient rna comparison across inputs saved in a 'profile_compare' folder

Code
====
"""
from ruffus import *
from ruffus.combinatorics import *
import sys
import os
from cgatcore import pipeline as P
import cgatcore.iotools as IOTools
from pathlib import Path
import pandas as pd
import yaml
import shutil

import cellhub.tasks as T

# -------------------------- Pipeline Configuration -------------------------- #

# Override function to collect config files
P.control.write_config_files = T.write_config_files

# load options from the yml file
P.parameters.HAVE_INITIALIZED = False
PARAMS = P.get_parameters(T.get_parameter_file(__file__))

# set the location of the code directory
PARAMS["cellhub_code_dir"] = Path(__file__).parents[1]

# ------------------------------ Pipeline Tasks ------------------------------ #


# ########################################################################### #
# ########################### Ambient RNA analysis ########################## #
# ########################################################################### #


# --------------------------------------------------------
# Run ambient rna analysis per input (e.g channel, library)

@transform("api/cellranger.multi/counts/unfiltered/*/mtx/matrix.mtx.gz",
           regex(r".*/.*/counts/unfiltered/(.*)/mtx/matrix.mtx.gz"),
           r"ambient.rna.dir/profile_per_input.dir/\1/ambient_rna.sentinel")
def ambient_rna_per_input(infile, outfile):
    '''Explore count and gene expression profiles of ambient RNA droplets per input
    - The output is saved in profile_per_input.dir/<input_id>
    - The output consists on a html report and a ambient_genes.txt.gz file
    - See more details of the output in the ambient_rna_per_library.R
    '''

    t = T.setup(infile, outfile, PARAMS, 
                memory=PARAMS["resources_job_memory"], 
                cpu=PARAMS["resources_threads"])

    library_id = str(Path(outfile).parents[0])

    # Create options dictionary
    options = {}
    options["umi"] = int(PARAMS["ambientRNA_umi"])
    options["cellranger_dir"] = t.indir
    options["outdir"] = t.outdir
    options["library_name"] = library_id

    # remove excludelisted cells if required
    if "excludelist" in PARAMS.keys():
    
        if PARAMS["excludelist"] is not None:
            options["excludelist"] = PARAMS["excludelist"]

    # Write yml file
    task_yaml_file = os.path.abspath(os.path.join(t.outdir,
                                                  "ambient_rna.yml"))

    with open(task_yaml_file, 'w') as yaml_file:
        yaml.dump(options, yaml_file)

    # Formulate and run statement
    statement = '''Rscript %(cellhub_code_dir)s/R/scripts/ambient_rna_per_library.R
                   --task_yml=%(task_yaml_file)s
                   --log_filename=%(log_file)s
                ''' % dict(PARAMS, **t.var, **locals())

    P.run(statement, **t.resources)
    
    IOTools.touch_file(outfile)


# ------------------------------------------------------------------
# Compare ambient rna profiles from all inputs (e.g channel, library)

@merge(ambient_rna_per_input,
       "ambient.rna.dir/profile_compare.dir/ambient_rna_compare.sentinel")
def ambient_rna_compare(infiles, outfile):
    '''Compare the expression of top ambient RNA genes across inputs
    - The output is saved in profile_compare.dir
    - Output includes and html report and a ambient_rna_profile.tsv
    - See more details of the output in the ambient_rna_compare.R
    '''

    t = T.setup(None, outfile, PARAMS, 
                memory=PARAMS["resources_job_memory"], 
                cpu=PARAMS["resources_threads"])

    library_indir = ",".join([os.path.dirname(x) for x in infiles])
    library_id = ",".join([str(os.path.basename(Path(x).parents[0]))
                           for x in infiles])

    # Create options dictionary
    options = {}
    options["library_indir"] = library_indir
    options["library_id"] = library_id
    options["library_table"] = "input_libraries.tsv"
    options["outdir"] = t.outdir

    # Write yml file
    task_yaml_file = os.path.abspath(os.path.join(t.outdir, "ambient_rna_compare.yml"))
    with open(task_yaml_file, 'w') as yaml_file:
        yaml.dump(options, yaml_file)

    # Formulate and run statement
    statement = '''Rscript %(cellhub_code_dir)s/R/scripts/ambient_rna_compare.R
                   --task_yml=%(task_yaml_file)s
                   --log_filename=%(log_file)s
                ''' % dict(PARAMS, **t.var, **locals())
    
    P.run(statement, **t.resources) 

    IOTools.touch_file(outfile)


# ----------------------
# Generic pipeline tasks

@follows(mkdir("ambient.rna.dir"))
@files(None, "ambient.rna.dir/plot.sentinel")
def plot(infile, outfile):
    '''Draw the pipeline flowchart'''

    pipeline_printout_graph ( "ambient.rna.dir/pipeline_flowchart.svg",
                          "svg",
                          [full],
                          no_key_legend=True)

    pipeline_printout_graph ( "ambient.rna.dir/pipeline_flowchart.png",
                          "png",
                          [full],
                          no_key_legend=True)

    IOTools.touch_file(outfile)


@follows(ambient_rna_compare, plot)
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
