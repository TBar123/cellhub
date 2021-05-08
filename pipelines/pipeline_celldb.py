'''
===============
Pipeline celldb
===============


Overview
========

This pipeline uploads the outputs from the upstream single-cell preprocessing
steps into a SQLite database.

Usage
=====

See :ref:`` and :ref:`` for general information on how to use cgat
pipelines.

Configuration
-------------

The pipeline requires a configured :file:`pipeline.yml` file.

Default configuration files can be generated by executing:
   cellhub celldb config

Input files
-----------

The pipeline requires the output of the pipelines:
    >> pipeline_cellranger.py : sample/10X-chip-channel x design-metadata
    >> pipeline_qc_metrics.py : barcode/cell x sequencing + mapping metadata
    >> pipeline_ambient_rna.py : gene/feature x sequencing + mapping metadata

pipeline generates a tsv configured file.

Dependencies
------------

Pipeline output
===============

The pipeline returns an SQLite populated database of metadata and
quality features that aid the selection of 'good' cells from 'bad' cells.

Currently the following tables are generated:
* metadata


Code
====

'''

from ruffus import *

import sys
import os
import re
import sqlite3
import pandas as pd
import numpy as np
import glob

import cgatcore.experiment as E
from cgatcore import pipeline as P
import cgatcore.iotools as iotools
import cgatcore.database as database

import tasks.control as C
import tasks.db as DB
import tasks.celldb as celldb

# Override function to collect config files
P.control.write_config_files = C.write_config_files

# load options from the yml file
parameter_file = C.get_parameter_file(__file__,__name__)
PARAMS = P.get_parameters(parameter_file)

def connect():
    '''connect to database.
    Use this method to connect to additional databases.
    Returns a database connection.
    '''

    dbh = database.connect(url=PARAMS["database_url"])

    return dbh

@follows(mkdir("celldb.dir"))
@originate("celldb.dir/sample.load")
def load_samples(outfile):
    ''' load the sample metadata table '''

    x = PARAMS["table_sample"]

    DB.load(x["name"],
            x["path"],
            db_url=PARAMS["database_url"],
            index = x["index"],
            outfile=outfile)


@follows(mkdir("celldb.dir"))
@originate("celldb.dir/libraries.load")
def load_libraries(outfile):
    ''' load the library metadata table '''

    x = PARAMS["table_library"]

    DB.load(x["name"],
            x["path"],
            db_url=PARAMS["database_url"],
            index = x["index"],
            outfile=outfile)


@jobs_limit(PARAMS.get("jobs_limit_db", 1), "db")
@originate("celldb.dir/cellranger_stats.load")
def load_cellranger_stats(outfile):
    '''load metadata of mapping data into database '''

    table_file = outfile.replace(".load", ".tsv")

    celldb.preprocess_cellranger_stats(
        PARAMS["table_library"]["path"],
        table_file)

    DB.load("cellranger_stats",
            table_file,
            db_url=PARAMS["database_url"],
            index = "library_id",
            outfile=outfile)


@jobs_limit(PARAMS.get("jobs_limit_db", 1), "db")
@originate("celldb.dir/gex_qcmetrics.load")
def load_gex_qcmetrics(outfile):
    '''load the gex qcmetrics into the database '''

    x = PARAMS["table_gex_qcmetrics"]

    DB.load(x["name"],
            x["path"],
            db_url=PARAMS["database_url"],
            glob=x["glob"],
            id_type=x["id_type"],
            index = x["index"],
            outfile=outfile)


@jobs_limit(PARAMS.get("jobs_limit_db", 1), "db")
@originate("celldb.dir/scrublet.load")
def load_gex_scrublet(outfile):
    '''load the scrublet scores into database '''

    x = PARAMS["table_gex_scrublet"]

    DB.load(x["name"],
            x["path"],
            db_url=PARAMS["database_url"],
            glob=x["glob"],
            id_type=x["id_type"],
            index = x["index"],
            outfile=outfile)


@follows(load_samples,
         load_libraries,
         load_gex_qcmetrics,
         load_gex_scrublet,
         load_cellranger_stats)
@jobs_limit(PARAMS.get("jobs_limit_db", 1), "db")
@originate("celldb.dir/final.sentinel")
def final(outfile):
    ''' '''

    dbh = connect()

    # the mapping metadata isn't needed here.
    # LEFT JOIN cellranger_statistics mm \

    s = PARAMS["table_sample"]["name"]
    l = PARAMS["table_library"]["name"]
    gex_qc = PARAMS["table_gex_qcmetrics"]["name"]
    gex_scrub = PARAMS["table_gex_scrublet"]["name"]
    lib = PARAMS["table_library"]["name"]

    statement = "CREATE VIEW final AS \
                 SELECT s.*, l.*, qc.*, scrub.* \
                 FROM %(l)s l \
                 LEFT JOIN %(gex_qc)s qc \
                 ON qc.library_id = l.library_id \
                 LEFT JOIN %(s)s s \
                 on qc.library_id = s.library_id \
                 LEFT JOIN %(gex_scrub)s scrub \
                 ON qc.barcode_id = scrub.barcode_id" % locals()

    cc = database.executewait(dbh, statement, retries=5)

    cc.close()

    iotools.touch_file(outfile)


# ########################################################################### #
# ##################### full target: to run all tasks ####################### #
# ########################################################################### #

@follows(final)
def full():
    pass

def main(argv=None):
    if argv is None:
        argv = sys.argv
    P.main(argv)

if __name__ == "__main__":
    sys.exit(P.main(sys.argv))
