"""
====================
Pipeline ambient rna
====================

Overview
========
This pipeline performs the following steps:
* Analyse the ambient RNA profile in each input (eg. channel's or library's raw cellrange matrices)
* Compare ambient RNA profiles across inputs


Configuration
-------------
The pipeline requires a configured :file:`pipeline.yml` file.
Default configuration files can be generated by executing:
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
* (optional) blacklist - path to a file with cell_ids to blacklist

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

import tasks.ambient_rna as ambient_rna
import tasks.control as C

# Override function to collect config files
P.control.write_config_files = C.write_config_files

# -------------------------- < parse parameters > --------------------------- #

# load options from the yml file
parameter_file = C.get_parameter_file(__file__,__name__)
PARAMS = P.get_parameters(parameter_file)

# Set the location of the cellhub code directory
if "code_dir" not in PARAMS.keys():
    PARAMS["code_dir"] = Path(__file__).parents[1]
else:
    if PARAMS["code_dir"] != Path(__file__).parents[1]:
        raise ValueError("Could not set the location of "
                         "the pipeline code directory")

# ----------------------- < pipeline configuration > ------------------------ #

# handle pipeline configuration
if len(sys.argv) > 1:
        if(sys.argv[1] == "config") and __name__ == "__main__":
                    sys.exit(P.main(sys.argv))

# ########################################################################### #
# ######## Check input libraries file and that the input exists ############### #
# ########################################################################### #

@originate("input.check.sentinel")
def checkInputs(outfile):
    '''Check that input_libraries.tsv exists and the path given in the file
       is a valid directorys. '''

    if not os.path.exists(PARAMS["input_libraries"]):
        raise ValueError('File specifying the input libraries is not present.'
                         'The file needs to be named PARAMS["input_libraries"] ')

    libraries = pd.read_csv(PARAMS["input_libraries"], sep='\t')
    for p in libraries["raw_path"]:
        if not os.path.exists(p):
          raise ValueError('Input folder from cellranger run (outs/)'
                             ' does not exist.')
    IOTools.touch_file(outfile)

# ########################################################################### #
# ########################### Ambient RNA analysis ########################## #
# ########################################################################### #

# ------------------------------------------------------------------------
# Create output folder for each input (e.g channel, library) in "per_input"

@follows(checkInputs)
def genClusterJobs():
    ''' Generate cluster jobs for each library '''

    if(__name__ == "__main__"):

        libraries = pd.read_csv(PARAMS["input_libraries"], sep='\t')
        infile = None

        for library in libraries["library_id"]:
            outfolder = "ambient.rna.dir/profile_per_input.dir/" + library
            outfile = os.path.join(outfolder, "prep.sentinel")
            yield(infile, outfile)

    else:
        yield(None, None)

@follows(checkInputs)
@files(genClusterJobs)
def prepFolders(infile, outfile):
    ''' Prepare folder structure for libraries '''

    outdir = os.path.dirname(outfile)
    if not os.path.exists(outdir):
        os.makedirs(outdir)

    IOTools.touch_file(outfile)

# --------------------------------------------------------
# Run ambient rna analysis per input (e.g channel, library)

@transform(prepFolders,
           regex(r"ambient.rna.dir/profile_per_input.dir/(.*)/prep.sentinel"),
           add_inputs(PARAMS["input_libraries"]),
           r"ambient.rna.dir/profile_per_input.dir/\1/ambient_rna.sentinel")
def ambient_rna_per_input(infiles, outfile):
    '''Explore count and gene expression profiles of ambient RNA droplets per input
    - The output is saved in profile_per_input.dir/<input_id>
    - The output consists on a html report and a ambient_genes.txt.gz file
    - See more details of the output in the ambient_rna_per_library.R
    '''

    infile, input_libraries = infiles

    ambient_rna.per_input(infile, input_libraries, outfile, PARAMS)

    # Create sentinel file
    IOTools.touch_file(outfile)


# ------------------------------------------------------------------
# Compare ambient rna profiles from all inputs (e.g channel, library)

@merge(ambient_rna_per_input,
       "ambient.rna.dir/profile_compare.dir/ambient_rna_compare.sentinel")
def ambient_rna_compare(infile, outfile):
    '''Compare the expression of top ambient RNA genes across inputs
    - The output is saved in profile_compare.dir
    - Output includes and html report and a ambient_rna_profile.tsv
    - See more details of the output in the ambient_rna_compare.R
    '''

    ambient_rna.compare(infile, outfile, PARAMS)

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
