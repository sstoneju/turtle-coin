SHELL := /bin/sh
PYTHON := $(shell /usr/bin/which python3)

# user needs to set PACKAGE_BUCKET as env variable
LAMBDA_NAME := turtle-coin-api
PACKAGE_BUCKET ?= tyler-turtle
AWS_DEFAULT_REGION ?= ap-northeast-2

BUILD_DIR := dist
PACKAGED_TEMPLATES_DIR := $(BUILD_DIR)/packaged_templates

init:
	pip install pipenv --no-cache-dir
	pipenv --python 3.8
	pipenv sync
	pipenv sync --dev

clean:
	rm -rf dist

install:
	pipenv install

run.local:
	pipenv run python cal_signal.py

test:
	pipenv run python -m pytest -v tests/unit

pre-package: clean
	mkdir -p $(BUILD_DIR)/app
	cp -R config $(BUILD_DIR)/app
	cp -R common $(BUILD_DIR)/app
	cp -R lib $(BUILD_DIR)/app
	cp -R service $(BUILD_DIR)/app
	
	cp main.py $(BUILD_DIR)/app
	cp template.yaml $(BUILD_DIR)
	
	pipenv lock --requirements > $(BUILD_DIR)/requirements.txt
	pipenv run pip install -t $(BUILD_DIR)/app/lib -r $(BUILD_DIR)/requirements.txt

set-template:
	$(eval SOURCE_TEMPLATE := dist/template.yaml)
	$(eval PACKAGED_TEMPLATE := $(PACKAGED_TEMPLATES_DIR)/$(LAMBDA_NAME).yaml)

package: set-template pre-package
	mkdir -p $(PACKAGED_TEMPLATES_DIR)
	aws cloudformation package --template-file $(SOURCE_TEMPLATE) --s3-bucket $(PACKAGE_BUCKET) --output-template-file $(PACKAGED_TEMPLATES_DIR)/$$(basename $(PACKAGED_TEMPLATE))

deploy: set-template package
	# STAGE deploy
	aws cloudformation deploy --template-file $(PACKAGED_TEMPLATE) --stack-name $$(basename $(PACKAGED_TEMPLATE) .yaml) --capabilities CAPABILITY_IAM

deploy.prod: set-template package
	# PROD deploy
	aws cloudformation deploy --template-file $(PACKAGED_TEMPLATE) --stack-name $$(basename $(PACKAGED_TEMPLATE) .yaml) --capabilities CAPABILITY_IAM