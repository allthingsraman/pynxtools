#
# Copyright The NOMAD Authors.
#
# This file is part of NOMAD. See https://nomad-lab.eu for further info.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""This script runs the conversion routine using a selected reader and write out a Nexus file."""

import glob
import importlib.machinery
import importlib.util
import json
import logging
import os
import re
import sys
from typing import List, Tuple, Dict
import xml.etree.ElementTree as ET

import click

from nexusparser.tools.dataconverter.readers.base.reader import BaseReader
from nexusparser.tools.dataconverter import helpers
from nexusparser.tools.dataconverter.writer import Writer


logger = logging.getLogger(__name__)  # pylint: disable=C0103
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(sys.stdout))


def generate_template_from_nxdl(root, template, path=None):
    """Helper function to generate a template dictionary for given NXDL"""
    if path is None:
        root = helpers.get_first_group(root)
        path = ""

    tag = helpers.remove_namespace_from_tag(root.tag)

    if tag == "doc":
        return

    suffix = ""
    if "name" in root.attrib:
        suffix = root.attrib['name']
    elif "type" in root.attrib:
        nexus_class = helpers.convert_nexus_to_caps(root.attrib['type'])
        hdf5name = f"[{helpers.convert_nexus_to_suggested_name(root.attrib['type'])}]"
        suffix = f"{nexus_class}{hdf5name}"

    if tag == "attribute":
        suffix = f"@{suffix}"

    path = path + "/" + suffix

    # Only add fields or attributes to the dictionary
    if tag in ("field", "attribute"):
        template[path] = None

    # Only add units if it is a field and the the units are defined but not set to NX_UNITLESS
    if tag == "field" and ("units" in root.attrib.keys() and root.attrib["units"] != "NX_UNITLESS"):
        template[f"{path}/@units"] = None

    for child in root:
        generate_template_from_nxdl(child, template, path)


def get_reader(reader_name) -> BaseReader:
    """Helper function to get the reader object from it's given name"""
    path_prefix = f"{os.path.dirname(__file__)}{os.sep}" if os.path.dirname(__file__) else ""
    path = os.path.join(path_prefix, "readers", reader_name, "reader.py")
    spec = importlib.util.spec_from_file_location("reader.py", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module.READER  # type: ignore[attr-defined]


def get_names_of_all_readers() -> List[str]:
    """Helper function to populate a list of all available readers"""
    path_prefix = f"{os.path.dirname(__file__)}{os.sep}" if os.path.dirname(__file__) else ""
    files = glob.glob(os.path.join(path_prefix, "readers", "*", "reader.py"))
    all_readers = []
    for file in files:
        if f"{os.sep}base{os.sep}" not in file:
            index_of_readers_folder_name = file.rindex(f"readers{os.sep}") + len(f"readers{os.sep}")
            index_of_last_path_sep = file.rindex(os.sep)
            all_readers.append(file[index_of_readers_folder_name:index_of_last_path_sep])
    return all_readers


@click.command()
@click.option(
    '--input-file',
    default=[],
    multiple=True,
    help='The path to the input data file to read. (Repeat for more than one file.)'
)
@click.option(
    '--reader',
    default='example',
    type=click.Choice(get_names_of_all_readers(), case_sensitive=False),
    help='The reader to use. default="example"'
)
@click.option(
    '--nxdl',
    default=None,
    required=True,
    help='The path to the corresponding NXDL file.'
)
@click.option(
    '--output',
    default='output.nxs',
    help='The path to the output Nexus file to be generated.'
)
@click.option(
    '--generate-template',
    is_flag=True,
    default=False,
    help='Just print out the template generated from given NXDL file.'
)
def convert(input_file: Tuple[str], reader: str, nxdl: str, output: str, generate_template: bool):
    """The conversion routine that takes the input parameters and calls the necessary functions."""
    # Reading in the NXDL and generating a template
    nxdl_root = ET.parse(nxdl).getroot()

    template: Dict[str, str] = {}
    generate_template_from_nxdl(nxdl_root, template)
    if generate_template:
        template.update((key, "None") for key in template)
        logger.info(json.dumps(template, indent=4, sort_keys=True))
        return

    # Setting up all the input data
    bulletpoint = "\n\u2022 "
    print_input_files = bulletpoint.join((" ", *input_file))
    logger.info("Using %s reader to convert the given files: %s ", reader, print_input_files)

    data_reader = get_reader(reader)
    nxdl_name = re.search("NX[a-z_]*(?=.nxdl.xml)", nxdl).group(0)
    if nxdl_name not in data_reader.supported_nxdls:
        raise Exception("The chosen NXDL isn't supported by the selected reader.")
    data = data_reader().read(template=dict(template),
                              file_paths=input_file)  # type: ignore[operator]

    helpers.validate_data_dict(template, data, nxdl_root)

    # Writing the data to output file
    Writer(data=data, nxdl_path=nxdl, output_path=output).write()

    logger.info("The output file generated: %s", output)


if __name__ == '__main__':
    convert()  # pylint: disable=no-value-for-parameter