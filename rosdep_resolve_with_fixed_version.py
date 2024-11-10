"""
Copyright (c) 2024 Dean.K
Distributed under the MIT License (http://opensource.org/licenses/MIT)
"""

import argparse
import glob
import xml.etree.ElementTree as ET
from typing import Dict, List
import subprocess
import os
import re

dependency_tags: List[str] = [
  'build_depend',
  'build_export_depend',
  'buildtool_depend',
  'buildtool_export_depend',
  'exec_depend',
  'depend',
  'doc_depend',
  'test_depend'
]

supported_version_attributes: List[str] = [
  'version_eq',
]

unsupported_version_attributes: List[str] = [
  'version_gte',
  'version_gt',
  'version_lte',
  'version_lt'
]

def rosdep_key_and_resolve(path: str):
  command = ['rosdep', 'keys', '--ignore-src', '--from-paths', f'"{path}"', '|', 'xargs', 'rosdep', 'resolve', '--rosdistro', f'{os.environ["ROS_DISTRO"]}']
  # 
  result = subprocess.run(' '.join(command), shell=True, capture_output=True, text=True, env=os.environ)
  if result.returncode == 0:
    print("Command succeeded:\n", result.stdout)
  else:
      print("Command failed:", result.stderr)
      raise RuntimeError(f'rosdep Command failed {result.stderr}')
  lines = [line for line in result.stdout.split('\n') if line.strip() != ''] 
  return lines

class RosdepResolvedPackageInfo:
  def __init__(self, ros_pkg_name: str, method: str, resolved_name: str):
    self.ros_pkg_name: str = ros_pkg_name
    self.method: str = method
    self.resolved_name: str = resolved_name
    self.target_versions: List[str] = []
      
def parse_rosdep(lines: List[str]) -> Dict[str, RosdepResolvedPackageInfo]:
  rosdep_head_pattern = re.compile(r'#ROSDEP\[(.*?)\]')
  method_pattern = re.compile(r'#(apt|pip)')

  package_info_list: List[RosdepResolvedPackageInfo] = []

  for line in lines:
    rosdep_head_match = rosdep_head_pattern.search(line)
    if rosdep_head_match:      
      package_info_list.append(RosdepResolvedPackageInfo(rosdep_head_match.group(1), method='', resolved_name=''))
      continue
    package_install_method_match = method_pattern.search(line)
    if package_install_method_match:
      if len(package_info_list) == 0:
        raise RuntimeError(f'Error: Method found before package name in rosdep result')
      package_info_list[-1].method = package_install_method_match.group(1)
      continue
    else:
      if len(package_info_list) == 0:
        raise RuntimeError(f'Error: resolved package name found before package name in rosdep result')
      package_info_list[-1].resolved_name = line

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
          print(f'WARNING: Unsupported version attribute found, ignore this attribute: {attr}/{dep.text} in package {path}')          
      for attr in supported_version_attributes:
        if attr in dep.attrib:
          if dep.text in dependencies:
            raise RuntimeError(f'ERROR: Duplicated dependency version found ({dependencies[dep.text]} and {dep.attrib[attr]}): {dep.text} in package {path}')
          dependencies[dep.text] = dep.attrib[attr]
  return dependencies

def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--from-paths", type=str, default="/home/dean/workspace/ros2/ufactorylite_ws/src/xarm_ros2") # , required=True
  # output
  parser.add_argument("--output-apt", type=str, default="", required=False)
  parser.add_argument("--output-pip", type=str, default="", required=False)

  args = parser.parse_args()
  print(f'root path: {args.from_paths}')

  rosdep_result = rosdep_key_and_resolve(args.from_paths)
  resolved_package_list =  parse_rosdep(rosdep_result)
  for key, package in resolved_package_list.items():
    print(f"Resolved package: {package.ros_pkg_name} version {package.target_versions} by {package.method} as {package.resolved_name}")

  package_xmls = collect_package_xml_path(args.from_paths)
  for package_xml in package_xmls:
    print(f"Found package.xml at {package_xml}")
    fixed_version_depends = extract_fixed_version_depend_from_package_xml(package_xml)
    print(fixed_version_depends)
    for key, value in fixed_version_depends.items():
      if not key in resolved_package_list.keys():
        print(f"WARNING: Dependency {key} not resolved by rosdep")
        continue
      resolved_package_list[key].target_versions.append(value)
  
  print('----------------')
  for key, package in resolved_package_list.items():
    print(f"Resolved package: {package.ros_pkg_name} version {package.target_versions} by {package.method} as {package.resolved_name}")


  if args.output_apt != '':
    with open(args.output_apt, 'w') as f:
      for key, package in resolved_package_list.items():
        if package.method == 'apt':
          if len(package.target_versions) == 0:
            text = f"{package.resolved_name}\n"
          elif len(package.target_versions) == 1:
            text = f"{package.resolved_name}={package.target_versions[0]}\n"
          else:
            print(f"Error: Multiple target versions found for apt package {package.ros_pkg_name}")
            raise RuntimeError(f"Error: Multiple target versions found for apt package {package.ros_pkg_name}")
          f.write(text)
  if args.output_pip != '':
    with open(args.output_pip, 'w') as f:
      for key, package in resolved_package_list.items():
        if package.method == 'pip':
          if len(package.target_versions) == 0:
            text = f"{package.resolved_name}\n"
          elif len(package.target_versions) == 1:
            text = f"{package.resolved_name}=={package.target_versions[0]}\n"
          else:
            print(f"Error: Multiple target versions found for apt package {package.ros_pkg_name}")
            raise RuntimeError(f"Error: Multiple target versions found for apt package {package.ros_pkg_name}")
          f.write(text)

if __name__ == "__main__":
  try:
    main()
  except Exception as e:
    print(e)
    exit(1)
