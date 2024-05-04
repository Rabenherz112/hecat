"""github_metadata processor
Gathers project/repository metadata from GitHub API and adds some fields to YAML data (`updated_at`, `stargazers_count`, `archived`).

# hecat.yml
steps:
  - step: process
    module: processors/github_metadata
    module_options:
      source_directory: tests/awesome-selfhosted-data # directory containing YAML data and software subdirectory
      gh_metadata_only_missing: False # (default False) only gather metadata for software entries in which one of stargazers_count,updated_at, archived is missing
      sleep_time: 3.7 # (default 0) sleep for this amount of time before each request to Github API

source_directory: path to directory where data files reside. Directory structure:
├── software
│   ├── mysoftware.yml # .yml files containing software data
│   ├── someothersoftware.yml
│   └── ...
├── platforms
├── tags
└── ...

A Github access token (without privileges) must be defined in the `GITHUB_TOKEN` environment variable:
$ GITHUB_TOKEN=AAAbbbCCCdd... hecat -c .hecat.yml
On Github Actions a token is created automatically for each job. To make it available in the environment use the following workflow configuration:
# .github/workflows/ci.yml
env:
  GITHUB_TOKEN: ${{secrets.GITHUB_TOKEN}}

When using GITHUB_TOKEN, the API rate limit is 1,000 requests per hour per repository [[1]](https://docs.github.com/en/rest/overview/resources-in-the-rest-api?apiVersion=2022-11-28#rate-limits-for-requests-from-github-actions)
Not that each call to get_gh_metadata() results in 2 API requests (on for the repo/stargazers count, one for the latest commit date)
"""

import sys
import logging
import requests
import re
import json
import os
import time
from datetime import datetime
import ruamel.yaml
import github
from ..utils import load_yaml_data, to_kebab_case

yaml = ruamel.yaml.YAML(typ='rt')
yaml.indent(sequence=4, offset=2)
yaml.width = 99999

class DummyGhMetadata(dict):
    """a dummy metadata object that will be returned when fetching metadata from github API fails"""
    def __init__(self):
        self.stargazers_count = 0
        self.archived = False
        self.current_release = {
            "tag": None,
            "published_at": None
        }
        self.last_commit_date = None
        self.commit_history = {}

def write_software_yaml(step, software):
    """write software data to yaml file"""
    dest_file = '{}/{}'.format(
                               step['module_options']['source_directory'] + '/software',
                               to_kebab_case(software['name']) + '.yml')
    logging.debug('writing file %s', dest_file)
    with open(dest_file, 'w+', encoding="utf-8") as yaml_file:
        yaml.dump(software, yaml_file)

def add_github_metadata(step):
    """gather github project data and add it to source YAML files"""
    GITHUB_TOKEN = os.environ['GITHUB_TOKEN']
    errors = []
    github_projects = []
    # Load software data
    software_list = load_yaml_data(step['module_options']['source_directory'] + '/software')
    logging.info('updating software data from Github API')
    # Check if the source code URL is a GitHub repository and add it to the queue to be processed
    for software in software_list:
        if 'source_code_url' in software:
            if re.search(r'^https://github.com/[\w\.\-]+/[\w\.\-]+/?$', software['source_code_url']):
                # Check if we only want to update missing metadata or all metadata
                if 'gh_metadata_only_missing' in step['module_options'].keys() and step['module_options']['gh_metadata_only_missing']:
                    if ('stargazers_count' not in software) or ('updated_at' not in software) or ('archived' not in software) or ('current_release' not in software) or ('last_commit_date' not in software) or ('commit_history' not in software):
                        github_projects.append(software)
                    else:
                        logging.debug('all metadata already present, skipping %s', software['source_code_url'])
                # If key is not present, update all metadata
                else:
                    github_projects.append(software)
        # TODO: Why do we need to check the website_url? We can exspect that the source_code_url is always present and the website_url is optional and even if changed it would not point to a github repository
        elif 'website_url' in software:
            if re.search(r'^https://github.com/[\w\.\-]+/[\w\.\-]+/?$' , software['website_url']):
                # Check if we only want to update missing metadata or all metadata
                if 'gh_metadata_only_missing' in step['module_options'].keys() and step['module_options']['gh_metadata_only_missing']:
                    if ('stargazers_count' not in software) or ('updated_at' not in software) or ('archived' not in software) or ('current_release' not in software) or ('last_commit_date' not in software) or ('commit_history' not in software):
                        github_projects.append(software)
                    else:
                        logging.debug('all metadata already present, skipping %s', software['website_url'])
                # If key is not present, update all metadata
                else:
                    github_projects.append(software)
    # Get the metadata for the GitHub repositories
    GITHUB_GRAPHQL_API = "https://api.github.com/graphql"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}

    # Get the URLs of the queued repositories
    github_urls = [software['source_code_url'] for software in github_projects]
    repos = [re.sub('https://github.com/', '', url) for url in github_urls]
    projectindex = 0

    # Split the list of repositories into batches of 60
    # TODO: While more should be supported, I don't get it to work with 75 or more, as the API returns an error
    n = 60
    batches = [repos[i * n:(i + 1) * n] for i in range((len(repos) + n - 1) // n )]


    for batch in batches:
        repos_query = " ".join([f"repo:{repo}" for repo in batch])

        # Get the current year and month
        now = datetime.now()
        year_month = now.strftime("%Y-%m")

        query = f"""
        {{
          search(
            type: REPOSITORY
            query: "{repos_query}"
            first: 60
          ) {{
            repos: edges {{
              repo: node {{
                ... on Repository {{
                  name
                  stargazerCount
                  isArchived
                  releases(first: 1) {{
                    edges {{
                      node {{
                        tagName
                        publishedAt
                      }}
                    }}
                  }}
                  defaultBranchRef {{
                    target {{
                      ... on Commit {{
                        committedDate
                        history(since: "{year_month}-01T00:00:00", until: "{year_month}-31T23:59:59") {{
                          totalCount
                        }}
                      }}
                    }}
                  }}
                }}
              }}
            }}
          }}
        }}
        """
        try:
            response = requests.post(GITHUB_GRAPHQL_API, json={"query": query}, headers=headers)
            data = response.json()
            if 'errors' in data:
                for error in data['errors']:
                    errors.append(error['message'])
                sys.exit(1)
        except Exception as e:
            errors.append(str(e))

        for edge in data["data"]["search"]["repos"]:
            repo = edge["repo"]
            software = github_projects[projectindex]
            software["stargazers_count"] = repo["stargazerCount"]
            software["archived"] = repo["isArchived"]
            if repo["releases"]["edges"] and len(repo["releases"]["edges"]) > 0:
                software["current_release"] = {
                    "tag": repo["releases"]["edges"][0]["node"]["tagName"],
                    "published_at": datetime.strptime(repo["releases"]["edges"][0]["node"]["publishedAt"], '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d')
                }
            software["updated_at"] = datetime.strptime(repo["defaultBranchRef"]["target"]["committedDate"], '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d')
            if 'commit_history' not in software:
                software['commit_history'] = {}
            if year_month in software["commit_history"]:
                software["commit_history"][year_month] = repo["defaultBranchRef"]["target"]["history"]["totalCount"]
            else:
                software["commit_history"].update({
                    year_month: repo["defaultBranchRef"]["target"]["history"]["totalCount"]
                })
            projectindex += 1
            write_software_yaml(step, software)

        # Sleep for the specified amount of time before the next request
        if 'sleep_time' in step['module_options']:
            time.sleep(step['module_options']['sleep_time'])
    
    if errors:
        logging.error("There were errors during processing")
        print('\n'.join(errors))
        sys.exit(1)

def gh_metadata_cleanup(step):
    """remove github metadata from source YAML files"""
    software_list = load_yaml_data(step['module_options']['source_directory'] + '/software')
    logging.info('cleaning up old github metadata from software data')
    # Get the current year and month
    now = datetime.now()
    year_month_12_months_ago = (now.replace(year = now.year - 1)).strftime("%Y-%m")
    # Check if commit_history exists and remove any entries that are older the 12 months
    for software in software_list:
        if 'commit_history' in software:
            for key in list(software['commit_history'].keys()):
                if key < year_month_12_months_ago:
                    del software['commit_history'][key]
                    logging.debug('removing commit history %s for %s', key, software['name'])
        write_software_yaml(step, software)
