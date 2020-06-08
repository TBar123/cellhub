"""

==============================================
Pipeline demultiplexing parser
==============================================
:Author: Fabiola Curion
:Date: |today|

Configuration
-------------
The pipeline requires a configured :file:`pipeline.yml` file.
Default configuration files can be generated by executing:
   python <srcdir>/pipeline_geneticdemultiplexing.py config

"""

import os
import sys
from pathlib import Path
import ruffus
from ruffus import *
import cgatcore.iotools as IOTools
from cgatcore import pipeline as P



# -------------------------- < parse parameters > --------------------------- #

# load options from the config file
PARAMS = P.get_parameters(
    ["%s/pipeline.yml" % os.path.splitext(__file__)[0],
     "../pipeline.yml",
     "pipeline.yml"])


# set the location of the pipeline code directory
if "cellhub_dir" not in PARAMS.keys():
    PARAMS["cellhub_dir"] = Path(__file__).parents[1]
else:
    raise ValueError("Could not set the location of the cellhub code directory")

# ----------------------- < pipeline configuration > ------------------------ #                             
 
# handle pipeline configuration                                                                             
if len(sys.argv) > 1:
        if(sys.argv[1] == "config") and __name__ == "__main__":
                    sys.exit(P.main(sys.argv))
 
# ########################################################################### #
# ############ Read in pipeline yml configuration params #################### #
# ########################################################################### #

baseoutdir=PARAMS["general_rundir"]

if not os.path.exists(baseoutdir):        
    os.mkdir(baseoutdir)

os.chdir(baseoutdir)

# ########################################################################### #
# ############################# pipeline tasks ############################## #
# ########################################################################### #


@originate("parsechannel.sentinel")
def parsechannel(outfile):
    samples_str=str(PARAMS["channel_sample"])
    basedir=PARAMS["channel_basedir"]
    demultiplexing=PARAMS["channel_demultiplexing"]
    subset=PARAMS["channel_subset"]
    job_threads = PARAMS["channel_numcpu"]
    
    samples = samples_str.strip().replace(" ", "").split(",")
    os.mkdir("results.channel.dir")
    os.chdir("results.channel.dir")
    statements = []    
    for sam in samples: 
        outdir= "results." + sam
        
        if not os.path.exists(outdir):        
            os.mkdir(outdir)
        
        logfile = "channel.parser.log"
        cellhub_dir = PARAMS["cellhub_dir"] 
        statements.append('''Rscript %(cellhub_dir)s/R/parse_genetic_multiplexing.R 
                                --basedir=%(basedir)s
                                --demultiplexing=%(demultiplexing)s
                                --samplename=%(sam)s
                                --subset=%(subset)s
                                --outdir=%(outdir)s
                                &> %(outdir)s/%(logfile)s
                          ''' % locals())     
        P.run(statements)
    IOTools.touch_file(outfile)

os.chdir('../')

@follows(parsechannel)
#prob not transform ???
@transform(parsechannel,
           regex(r"parsechannel.sentinel"),
           r"project.parser.sentinel")
def reportall(infile,outfile):
    
    project=PARAMS["project_project"]
    
    outdir= "results." + project + ".dir"
    if not os.path.exists(outdir):
        os.mkdir(outdir)
    
    samples=PARAMS["project_sampledir"]
    subset=PARAMS["project_subset"]
    #baseoutdir =PARAMS["project_basedir"] 
    baseoutdir = "results.channel.dir"
    job_threads = PARAMS["project_numcpu"]    
    logfile = "project.parser.log"
    
    
    statement = '''Rscript %(cellhub_dir)s/R/parse_project_multiplexing.R 
                            --basedir=%(baseoutdir)s
                            --samplename=%(samples)s
                            --subset=%(subset)s 
                            --outdir=%(outdir)s
                            &> %(outdir)s/%(logfile)s
                '''
    P.run(statement)
    
    

# ########################################################################### #                             
# ##################### full target: to run all tasks ####################### #                             
# ########################################################################### #                             
@follows(reportall) 
def full():
    '''
    Run the full pipeline.
    '''
    pass
 
# ------------------- < ***** end of pipeline **** > ------------------------ #                             
 
if __name__ == "__main__":
    sys.exit(P.main(sys.argv))