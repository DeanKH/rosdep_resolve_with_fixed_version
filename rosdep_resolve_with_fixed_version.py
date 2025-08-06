#!/usr/bin/env python3
"""
Copyright (c) 2024 Dean.K
Distributed under the MIT License (http://opensource.org/licenses/MIT)
"""

from optparse import OptionParser
import glob
import xml.etree.ElementTree as ET
from typing import Dict, List
import subprocess
import os
import re
import sys

dependency_tags: List[str] = [
    "build_depend",
    "build_export_depend",
    "buildtool_depend",
    "buildtool_export_depend",
    "exec_depend",
    "depend",
    "doc_depend",
    "test_depend",
]

supported_version_attributes: List[str] = [
    "version_eq",
]

unsupported_version_attributes: List[str] = [
    "version_gte",
    "version_gt",
    "version_lte",
    "version_lt",
]


def run_rosdep_key(
    path: str, dependency_types: List[str], contain_src: bool
) -> List[str]:
    dependncy_str = ""
    if len(dependency_types) != 0:
        for dep_type in dependency_types:
            dependncy_str += f"--dependency-types {dep_type} "

    command = [
        "rosdep",
        "keys",
        "--ignore-src" if not contain_src else "",
        "--from-paths",
        f'"{path}"',
        f"{dependncy_str}",
    ]

    result = subprocess.run(
        " ".join(command), shell=True, capture_output=True, text=True, env=os.environ
    )
    if result.returncode == 0:
        rosdep_packages = [
            line for line in result.stdout.split("\n") if line.strip() != ""
        ]
    return rosdep_packages


def rosdep_key_and_resolve(path: str, dependency_types: List[str], contain_src: bool):
    rosdep_packages = run_rosdep_key(path, dependency_types, contain_src)
    lines = []
    for rosdep_package in rosdep_packages:
        command = [
            "rosdep",
            "resolve",
            "--rosdistro",
            f'{os.environ["ROS_DISTRO"]}',
            f"{rosdep_package}",
        ]
        # print("running rosdep command: ", " ".join(command))
        result = subprocess.run(
            " ".join(command),
            shell=True,
            capture_output=True,
            text=True,
            env=os.environ,
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip("\n")
            print(f"SKIP package: {rosdep_package}, {error_msg}")
            # raise RuntimeError(f"rosdep Command failed {result.stderr}")
            continue
        each_package = [
            line for line in result.stdout.split("\n") if line.strip() != ""
        ]
        each_package.insert(0, f"#ROSDEP[{rosdep_package}]")
        lines.extend(each_package)
    return lines


class RosdepResolvedPackageInfo:
    def __init__(self, ros_pkg_name: str, method: str, resolved_names: List[str]):
        self.ros_pkg_name: str = ros_pkg_name
        self.method: str = method
        self.resolved_names: List[str] = resolved_names
        self.target_versions: List[str] = []


def parse_rosdep(lines: List[str]) -> Dict[str, RosdepResolvedPackageInfo]:
    rosdep_head_pattern = re.compile(r"#ROSDEP\[(.*?)\]")
    method_pattern = re.compile(r"#(apt|pip)")

    package_info_list: List[RosdepResolvedPackageInfo] = []

    for line in lines:
        rosdep_head_match = rosdep_head_pattern.search(line)
        if rosdep_head_match:
            package_info_list.append(
                RosdepResolvedPackageInfo(
                    rosdep_head_match.group(1), method="", resolved_names=[]
                )
            )
            continue
        package_install_method_match = method_pattern.search(line)
        if package_install_method_match:
            if len(package_info_list) == 0:
                raise RuntimeError(
                    f"Error: Method found before package name in rosdep result"
                )
            package_info_list[-1].method = package_install_method_match.group(1)
            continue
        else:
            if len(package_info_list) == 0:
                raise RuntimeError(
                    f"Error: resolved package name found before package name in rosdep result"
                )
            package_info_list[-1].resolved_names = line.split(" ")

    # convert list to dict with key as ros_pkg_name
    package_info_dict = {package.ros_pkg_name: package for package in package_info_list}
    package_info_dict = dict(sorted(package_info_dict.items()))
    return package_info_dict


def collect_package_xml_path(path: str) -> List[str]:
    package_xmls = glob.glob(f"{path}/**/package.xml", recursive=True)
    return package_xmls


def extract_fixed_version_depend_from_package_xml(path: str) -> Dict[str, str]:
    xml = ET.parse(path)
    root = xml.getroot()

    dependencies: Dict[str, str] = {}
    for tag in dependency_tags:
        for dep in root.findall(tag):
            for attr in unsupported_version_attributes:
                if attr in dep.attrib:
                    print(
                        f"WARNING: Unsupported version attribute found, ignore this attribute: {attr}/{dep.text} in package {path}"
                    )
            for attr in supported_version_attributes:
                if attr in dep.attrib:
                    if dep.text in dependencies:
                        raise RuntimeError(
                            f"ERROR: Duplicated dependency version found ({dependencies[dep.text]} and {dep.attrib[attr]}): {dep.text} in package {path}"
                        )
                    dependencies[dep.text] = dep.attrib[attr]
    return dependencies


def main(args):
    parser = OptionParser(usage="", prog="rosdep-with-v")
    parser.add_option(
        "--fixed-package-list", dest="fixed_package_xml", type=str, default=""
    )
    parser.add_option(
        "--from-paths", dest="from_paths", type=str, default=""
    )  # , required=True
    parser.add_option("--output-apt", dest="output_apt", type=str, default="")
    parser.add_option("--output-pip", dest="output_pip", type=str, default="")
    parser.add_option(
        "--contain-src", dest="contain_src", action="store_true", default=False
    )
    parser.add_option(
        "--dependency-types",
        dest="dependency_types",
        default=[],
        action="append",
        choices=list(
            {
                "build",
                "buildtool",
                "build_export",
                "buildtool_export",
                "exec",
                "test",
                "doc",
            }
        ),
    )
    options, args = parser.parse_args(args)
    options.dependency_types = [
        dep for s in options.dependency_types for dep in s.split(" ")
    ]

    # print(f"root path: {options.from_paths}")

    rosdep_result = rosdep_key_and_resolve(
        options.from_paths, options.dependency_types, options.contain_src
    )
    resolved_package_list = parse_rosdep(rosdep_result)
    # for key, package in resolved_package_list.items():
    # print(
    #     f"Resolved package: {package.ros_pkg_name} version {package.target_versions} by {package.method} as {package.resolved_names}"
    # )

    # package_xmls = collect_package_xml_path(options.from_paths)
    # for package_xml in package_xmls:
    # print(f"Found package.xml at {package_xml}")

    if len(options.fixed_package_xml) != 0:
        fixed_version_depends = extract_fixed_version_depend_from_package_xml(
            options.fixed_package_xml
        )
        print(fixed_version_depends)
        for key, value in fixed_version_depends.items():
            if not key in resolved_package_list.keys():
                continue
            resolved_package_list[key].target_versions.append(value)

    # print("----------------")
    for key, package in resolved_package_list.items():
        print(
            f"Resolved package: {package.ros_pkg_name} version {package.target_versions} by {package.method} as {package.resolved_names}"
        )

    if options.output_apt != "":
        with open(options.output_apt, "w") as f:
            for key, package in resolved_package_list.items():
                if package.method == "apt":
                    text = ""
                    if len(package.target_versions) == 0:
                        for item in package.resolved_names:
                            text += f"{item}\n"
                    elif len(package.target_versions) == 1:
                        for item in package.resolved_names:
                            text += f"{item}={package.target_versions[0]}\n"
                    else:
                        print(
                            f"Error: Multiple target versions found for apt package {package.ros_pkg_name}"
                        )
                        raise RuntimeError(
                            f"Error: Multiple target versions found for apt package {package.ros_pkg_name}"
                        )
                    f.write(text)
    if options.output_pip != "":
        with open(options.output_pip, "w") as f:
            for key, package in resolved_package_list.items():
                if package.method == "pip":
                    text = ""
                    if len(package.target_versions) == 0:
                        for item in package.resolved_names:
                            text += f"{item}\n"
                    elif len(package.target_versions) == 1:
                        for item in package.resolved_names:
                            text += f"{item}=={package.target_versions[0]}\n"
                    else:
                        print(
                            f"Error: Multiple target versions found for apt package {package.ros_pkg_name}"
                        )
                        raise RuntimeError(
                            f"Error: Multiple target versions found for apt package {package.ros_pkg_name}"
                        )
                    f.write(text)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as e:
        print(e)
        exit(1)
