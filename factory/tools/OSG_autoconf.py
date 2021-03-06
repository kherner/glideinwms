#!/usr/bin/env python
""" Allows to retrieve information from the OSG collector and generate the factory xml file
"""

from __future__ import division
from __future__ import print_function

import sys
import argparse
import fractions

import htcondor

from glideinwms.lib.config_util import ENTRY_STUB, GLIDEIN_SUPPORTED_VO_MAP, ProgramError, get_attr_str, update, \
     get_yaml_file_info, write_to_yaml_file, get_submit_attr_str, write_to_xml_file, get_limits_str, \
     get_submission_speed


def load_config():
    """Load few parameters from the configuration file
    """
    parser = argparse.ArgumentParser(prog='OSG_autoconf')
    parser.add_argument('config', nargs=1, help='The configuration file')
    args = parser.parse_args()

    config = get_yaml_file_info(args.config[0])

    return config


def get_vos(allowed_vos):
    """This function converts the list of VO from the collector to the frontend ones

    Args:
        allowed_vos (list): The list ov vos in the OSG collector

    Returns:
        set: The set of frontend VOs to add to the configuration GLIDEIN_SupportedVOs
    """
    vos = set()
    for vorg in allowed_vos:
        if vorg in GLIDEIN_SUPPORTED_VO_MAP:
            vos.add(GLIDEIN_SUPPORTED_VO_MAP[vorg])
        else:
            print(vorg + " VO is not in GLIDEIN_Supported_VOs_map")

    return vos


def get_information(host):
    """Query the OSG collector and get information about the known HTCondor-CE.

    The OSG collector is queried with the -sched option to get information about
    all the HTCondorCEs. The relevant OSG resource information is then organized
    in a dict.

    Args:
        host (str): The hostname where the OSG collector is running

    Returns:
        dict: A resource dictionary whose keys are the resources ('cedar', 'UCHICAGO', 'NMSU')
            and its values are the needed information to create the entry. For example:

            {'hosted-ce32.grid.uchicago.edu':
                     {'DEFAULT_ENTRY': {'attrs': {'GLIDEIN_CPUS': {'value': 16L},
                                                  'GLIDEIN_MaxMemMBs': {'value': 163840L},
                                                  'GLIDEIN_Max_Walltime': {'value': 171000L},
                                                  'GLIDEIN_ResourceName': {'value': 'NEMO'},
                                                  'GLIDEIN_Site': {'value': 'OSG_US_UWM_NEMO'},
                                                  'GLIDEIN_Supported_VOs': {'value': 'OSGVO'}},
                                        'gridtype': 'condor',
                                        'submit_attrs': {'+maxMemory': 163840L,
                                                         '+maxWallTime': 2880L,
                                                         '+xcount': 16L}}}}
    """
    collector = htcondor.Collector(host)
    ces = collector.query(htcondor.AdTypes.Schedd)
    result = {}
    entry = "DEFAULT_ENTRY"
    for celem in ces:
        if "OSG_ResourceGroup" in celem:
            resource = celem["OSG_ResourceGroup"] or celem["OSG_Resource"]
            site = celem["OSG_Resource"] # not used for now, but factory ops will add a new attribute 1in the future
            gatekeeper = celem["Name"].lower()
            if resource:
                if resource not in result:
                    result[resource] = {}
                result[resource][gatekeeper] = {}
                #TODO The following "if" should be put in a function to make pylint happy
                if "OSG_ResourceCatalog" in celem:
                    vos = set()
                    memory = sys.maxint
                    walltime = sys.maxint
                    cpus = ""
                    for osg_catalog in celem["OSG_ResourceCatalog"]:
                        if "AllowedVOs" in osg_catalog:
                            if len(vos) == 0:
                                vos = get_vos(osg_catalog["AllowedVOs"])
                            else:
                                vos = vos.intersection(get_vos(osg_catalog["AllowedVOs"]))
                        if "Memory" in osg_catalog:
                            memory = min(memory, osg_catalog["Memory"])
                        if "MaxWallTime" in osg_catalog:
                            walltime = min(walltime, osg_catalog["MaxWallTime"])
                        if "CPUs" in osg_catalog:
                            if cpus == "":
                                cpus = osg_catalog["CPUs"]
                            else:
                                cpus = fractions.gcd(cpus, osg_catalog["CPUs"])
                    # Assigning this to an entry dict variable to shorten the line
                    edict = {}
                    result[resource][gatekeeper][entry] = edict
                    edict["gridtype"] = "condor"
                    edict["attrs"] = {}
                    edict["attrs"]["GLIDEIN_Site"] = {"value": resource}
                    if resource:
                        edict["attrs"]["GLIDEIN_ResourceName"] = {"value": resource}
                    if len(vos) > 0:
                        edict["attrs"]["GLIDEIN_Supported_VOs"] = {"value": ",".join(vos)}
                    else:
                        print(gatekeeper + " CE does not have VOs")
                    edict["submit_attrs"] = {}
                    if cpus != "":
                        edict["attrs"]["GLIDEIN_CPUS"] = {"value": cpus}
                        edict["submit_attrs"]["+xcount"] = cpus
                    if walltime != sys.maxint:
                        glide_walltime = walltime * 60 - 1800
                        edict["attrs"]["GLIDEIN_Max_Walltime"] = {"value": glide_walltime}
                        edict["submit_attrs"]["+maxWallTime"] = walltime
                    if memory != sys.maxint:
                        edict["attrs"]["GLIDEIN_MaxMemMBs"] = {"value": memory}
                        edict["submit_attrs"]["+maxMemory"] = memory
                else:
                    print(gatekeeper + " CE does not have OSG_ResourceCatalog attribute")
            else:
                print(gatekeeper + " CE does not have OSG_ResourceGroup attribute")

    return result


def get_entries_configuration(data):
    """Given the dictionary of resources, returns the generated factory xml file

    Args:
        data (dict): A dictionary similar to the one returned by ``get_information``

    Returns:
        str: The factory xml file as a string
    """
    entries_configuration = ""
    for _, site_information in sorted(data.items()):
        for celem, ce_information in sorted(site_information.items()):
            for entry, entry_information in sorted(ce_information.items()):
                entry_configuration = entry_information
                entry_configuration["entry_name"] = entry
                # Can we get these information (next two keys)?
                entry_configuration["attrs"]["GLEXEC_BIN"] = {"value": "NONE"}
                entry_configuration["attrs"]["GLIDEIN_REQUIRED_OS"] = (
                    {"comment": "This value has been hardcoded", "value": "any"}
                )
                # Probably we can use port from attribute AddressV1 or CollectorHost
                entry_configuration["gatekeeper"] = celem + " " + celem + ":9619"
                entry_configuration["rsl"] = ""
                entry_configuration["attrs"] = get_attr_str(entry_configuration["attrs"])
                if "submit_attrs" in entry_configuration:
                    entry_configuration["submit_attrs"] = (
                        get_submit_attr_str(entry_configuration["submit_attrs"])
                    )
                else:
                    entry_configuration["submit_attrs"] = ""
                entry_configuration["limits"] = get_limits_str(entry_configuration["limits"])
                entry_configuration["submission_speed"] = get_submission_speed(entry_configuration["submission_speed"])
                entries_configuration += ENTRY_STUB % entry_configuration

    return entries_configuration


def merge_yaml(config, white_list):
    """Merges different yaml file and return the corresponding resource dictionary

    Three different yam files are merged. First we read the factory white list/override file that
    contains the list of entries operators want to generate, with the parameters they want to
    override.
    Then the yaml generated from the OSG collector and the default yam file are read.
    For each entry an all the operator information are "updated" with the information coming from
    the collector first, and from the default file next.

    Returns:
        dict: a dict similar to the one returned by ``get_information``, but with all the defaults
            and the operators overrides in place (only whitelisted entries are returned).
    """
    out = get_yaml_file_info(white_list)
    osg_info = get_yaml_file_info(config["OSG_YAML"])
    default_information = get_yaml_file_info(config["OSG_DEFAULT"])
    for site, site_information in out.items():
        if site_information is None:
            print("There is no site information for %s site in white list file." % site)
            del out[site]
            continue
        print("Merging %s" % site)
        if site not in osg_info:
            print("You put %s in the whitelist file, but the site is not present in the collector"
                  % site)
            raise ProgramError(2)
        for celem, ce_information in site_information.items():
            if ce_information is None:
                print("There is no CE information for %s CE in white list file." % celem)
                del out[site][celem]
                continue
            if celem not in osg_info[site]:
                print("Working on whitelisted site %s: cant find ce %s in the generated OSG.yaml"
                      % (site, celem))
                raise ProgramError(3)
            for entry, entry_information in ce_information.items():
                if entry_information is None:
                    out[site][celem][entry] = osg_info[site][celem]["DEFAULT_ENTRY"]
                    entry_information = out[site][celem][entry]
                else:
                    if osg_info[site][celem]["DEFAULT_ENTRY"]["gridtype"] == "condor":
                        if "attrs" in entry_information:
                            entry_information = update_submit_attrs(entry_information, "GLIDEIN_CPUS", "+xcount")
                            entry_information = update_submit_attrs(entry_information, "GLIDEIN_MaxMemMBs", "+maxMemory")
                            entry_information = update_submit_attrs(entry_information, "GLIDEIN_Max_Walltime", "+maxWallTime")
                    if "limits" in entry_information:
                        if "entry" in entry_information["limits"] and "frontend" not in entry_information["limits"]:
                            entry_information["limits"]["frontend"] = entry_information["limits"]["entry"]
                        elif "entry" not in entry_information["limits"] and "frontend" in entry_information["limits"]:
                            entry_information["limits"]["entry"] = entry_information["limits"]["frontend"]
                    update(entry_information, osg_info[site][celem]["DEFAULT_ENTRY"],
                           overwrite=False)
                update(
                    entry_information,
                    default_information["DEFAULT_SITE"]["DEFAULT_GETEKEEPER"]["DEFAULT_ENTRY"],
                    overwrite=False
                )
    return out


def update_submit_attrs(entry_information, attr, submit_attr):
    """Update submit attribute according to produced attribute if submit attribute is not defined

    Args:
        entry_information (dict): a dictionary of entry information from white list file
        attr (str): attribute name
        submit_attr: submit attribute name

    Returns:
        dict: a dictionary of entry iformation from white list file with possible updated submit attribute
    """
    if attr in entry_information["attrs"] and entry_information["attrs"][attr]:
        if "submit_attrs" in entry_information:
            if submit_attr not in entry_information["submit_attrs"]:
                if attr == "GLIDEIN_Max_Walltime":
                    entry_information["submit_attrs"][submit_attr] = int(entry_information["attrs"][attr]["value"] / 60) + 30
                else:
                    entry_information["submit_attrs"][submit_attr] = entry_information["attrs"][attr]["value"]
        else:
            entry_information["submit_attrs"] = {}
            if attr == "GLIDEIN_Max_Walltime":
                entry_information["submit_attrs"][submit_attr] = int(entry_information["attrs"][attr]["value"] / 60) + 30
            else:
                entry_information["submit_attrs"][submit_attr] = entry_information["attrs"][attr]["value"]

    return entry_information


def main():
    """The main"""
    config = load_config()
    # Queries the OSG collector
    result = get_information(config["OSG_COLLECTOR"])
    # Write the received information to the OSG.yml file
    write_to_yaml_file(config["OSG_YAML"], result)
    # Merges different yaml files: the defaults, the generated one, and the factory overrides
    for white_list in config["OSG_WHITELISTS"]:
        result = merge_yaml(config, white_list)
        # Convert the resoruce dictionary obtained this way into a string (xml)
        entries_configuration = get_entries_configuration(result)
        # Write the factory configuration file on the disk
        write_to_xml_file(white_list.replace("yml", "xml"), entries_configuration)


if __name__ == "__main__":
    try:
        main()
    except ProgramError as merr:
        print("\033[91mError! \033[0m" + ProgramError.codes_map[merr.code])
        sys.exit(merr.code)
    except:
        import logging
        logging.exception("")
        print("\033[91mUnexpected exception. Aborting automatic configuration generation!\033[0m")
        raise
    sys.exit(0)
