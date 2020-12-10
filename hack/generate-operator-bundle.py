#!/usr/bin/env python
#
# Generate an operator bundle for publishing to OLM. Copies appropriate files
# into a directory, and composes the ClusterServiceVersion which needs bits and
# pieces of our rbac and deployment files.
#
# Usage ./hack/generate-operator-bundle.py OUTPUT_DIR PREVIOUS_VERSION GIT_NUM_COMMITS GIT_HASH HIVE_IMAGE
#
# Commit count can be obtained with: git rev-list 9c56c62c6d0180c27e1cc9cf195f4bbfd7a617dd..HEAD --count
# This is the first hive commit, if we tag a release we can then switch to using that tag and bump the base version.

import subprocess
import tempfile
import datetime
import os
import sys
import yaml
import shutil

# This script will append the current number of commits given as an arg
# (presumably since some past base tag), and the git hash arg for a final
# version like: 0.1.189-3f73a592
VERSION_BASE = "0.1"

if len(sys.argv) != 6:
    print("USAGE: %s OUTPUT_DIR PREVIOUS_VERSION GIT_NUM_COMMITS GIT_HASH HIVE_IMAGE" %
          sys.argv[0])
    sys.exit(1)

outdir = sys.argv[1]
prev_version = sys.argv[2]
git_num_commits = sys.argv[3]
git_hash = sys.argv[4]
route-monitor-operator_image = sys.argv[5]

full_version = "%s.%s-%s" % (VERSION_BASE, git_num_commits, git_hash)
print("Generating CSV for version: %s" % full_version)

with open('bundle/manifests/route-monitor-operator.clusterserviceversion.yaml', 'r') as stream:
    csv = yaml.load(stream)

if not os.path.exists(outdir):
    os.mkdir(outdir)

version_dir = os.path.join(outdir, full_version)
if not os.path.exists(version_dir):
    os.mkdir(version_dir)

# Initialize CRD array in CSV
csv['spec']['customresourcedefinitions']['owned'] = []

# Copy all CSV files over to the bundle output dir:
kustomize_output = subprocess.run(
    ["kustomize", "build", "config/crd"], stdout=subprocess.PIPE).stdout
for crd in yaml.safe_load_all(kustomize_output):
    crd = yaml.load(stream)
    # Update CSV template customresourcedefinitions key
    csv['spec']['customresourcedefinitions']['owned'].append(
        {
            "name": crd["metadata"]["name"],
            "description": crd["spec"]["names"]["kind"],
            "displayName": crd["spec"]["names"]["kind"],
            "kind": crd["spec"]["names"]["kind"],
            "version": crd["spec"]["version"]
        }
    )

# Copy all prometheus yaml files over to the bundle output dir:

kustomize_yamls = subprocess.run(
    ["kustomize", "build", "config/prometheus"], stdout=subprocess.PIPE)

for extracted_yaml in yaml.safe_load_all(kustomize_yamls.stdout):
    with tempfile.NamedTemporaryFile(mode="w+t",
                                     prefix='prometheus_', suffix='.yaml',
                                     dir=version_dir,
                                     delete=False) as temp_file:
        yaml.dump(extracted_yaml, temp_file, default_flow_style=False)

csv['spec']['install']['spec']['clusterPermissions'] = []

# Add route-monitor-operator role to the CSV:
with open('deploy/cluster_role.yaml', 'r') as stream:
    operator_role = yaml.load(stream)
    csv['spec']['install']['spec']['clusterPermissions'].append(
        {
            'rules': operator_role['rules'],
            'serviceAccountName': 'route-monitor-operator',
        })

# Add route-monitor-operator-client role to the CSV:
with open('deploy/uhc_cluster_role.yaml', 'r') as stream:
    operator_role = yaml.load(stream)
    csv['spec']['install']['spec']['clusterPermissions'].append(
        {
            'rules': operator_role['rules'],
            'serviceAccountName': 'route-monitor-operator-client',
        })

# Add our deployment spec for the hive operator:
with open('deploy/operator.yaml', 'r') as stream:
    operator_components = []
    operator = yaml.load_all(stream)
    for doc in operator:
        operator_components.append(doc)
    # There is only one yaml document in the operator deployment
    operator_deployment = operator_components[0]
    csv['spec']['install']['spec']['deployments'][0]['spec'] = operator_deployment['spec']

# Update the deployment to use the defined image:
csv['spec']['install']['spec']['deployments'][0]['spec']['template']['spec']['containers'][0]['image'] = route-monitor-operator_image

# Update the versions to include git hash:
csv['metadata']['name'] = "route-monitor-operator.v%s" % full_version
csv['spec']['version'] = full_version
csv['spec']['replaces'] = "route-monitor-operator.v%s" % prev_version

# Set the CSV createdAt annotation:
now = datetime.datetime.now()
csv['metadata']['annotations']['createdAt'] = now.strftime(
    "%Y-%m-%dT%H:%M:%SZ")

# Write the CSV to disk:
csv_filename = "route-monitor-operator.v%s.clusterserviceversion.yaml" % full_version
csv_file = os.path.join(version_dir, csv_filename)
with open(csv_file, 'w') as outfile:
    yaml.dump(csv, outfile, default_flow_style=False)
print("Wrote ClusterServiceVersion: %s" % csv_file)
