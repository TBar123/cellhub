Usage
=====


Configuring and running pipelines
---------------------------------

Run the cellhub --help command to view the help documentation and find available pipelines to run cellhub.

The cellhub pipelines are written using `cgat-core <https://github.com/cgat-developers/cgat-core>`_ pipelining system. From more information please see the `CGAT-core paper <https://doi.org/10.12688/f1000research.18674.2>`_. Here we illustrate how the pipelines can be run using the cellranger pipeline as an example.

Following installation, to find the available pipelines run: ::

  cellhub -h

Next generate a configuration yml file: ::

  cellhub cellranger config -v5

To fully run the example cellhub pipeline run: ::

  cellhub cellranger make full -v5

However, it may be best to begin by running the individual tasks of the pipeline to get a feel of what each task is doing. To list the pipline tasks and their current status, use the 'show' command: ::

  cellhub cellranger show

Individual tasks can then be executed by name, e.g. ::

  cellhub cellranger make cellrangerMulti -v5

.. note:: If any upstream tasks are out of date they will automatically be run before the named task is executed.


Getting Started
---------------

To get started please see the :doc:`IFNb example</examples/ifnb>`. 

For an example configuration files for a multimodal immune profiling experiment please see the :doc:`PBMC 10k example</examples/pbmc10k>`.

