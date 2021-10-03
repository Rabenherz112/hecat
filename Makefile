SHELL := /bin/bash

.PHONY: clean # clean files generated by make install/test_run
clean:
	-rm -rf build/ dist/ hecat.egg-info/ awesome-selfhosted awesome-selfhosted-data

.PHONY: virtualenv # setup python virtualenv
virtualenv:
	python3 -m venv .venv

.PHONY: test # run tests
test: pylint test_run

.PHONY: pylint # run linter
pylint: install
	-source .venv/bin/activate && \
	pip3 install pylint pyyaml && \
	pylint --disable=too-many-locals hecat

.PHONY: install # install in a virtualenv
install: virtualenv
	source .venv/bin/activate && \
	python3 setup.py install

.PHONY: test_run # test import against actual data
test_run: install
	git clone --depth=1 https://github.com/awesome-selfhosted/awesome-selfhosted
	git clone --depth=1 https://github.com/awesome-selfhosted/awesome-selfhosted-data
	mkdir awesome-selfhosted-data/{tags,software,platforms}
	source .venv/bin/activate && \
	hecat import --source-file awesome-selfhosted/README.md --output-directory awesome-selfhosted-data && \
	hecat build --source-directory awesome-selfhosted-data --output-directory awesome-selfhosted --output-file README.md
	tree awesome-selfhosted-data
	cd awesome-selfhosted && git diff