IMAGE_NAME ?= research-analysis-layer
IMAGE_TAG ?= latest
CONTAINER_NAME ?= research-analysis-layer-hourly
ENV_FILE ?= $(if $(wildcard .env),.env,../research_parser/.env)
HOST_STATE_DB_PATH ?= ../research_parser/data/state.db
HOST_ANALYSIS_DIR ?= $(CURDIR)/data
HOST_PIPELINE_OPS_DIR ?= ../research_pipeline_ops
CONTAINER_STATE_DB_PATH ?= /parser-data/state.db
CONTAINER_ANALYSIS_DIR ?= /data
STATE_DB_PATH ?= $(CONTAINER_STATE_DB_PATH)
ANALYSIS_DB_URL ?= sqlite:///$(CONTAINER_ANALYSIS_DIR)/analysis.db
POLL_INTERVAL_SECONDS ?= 3600
RUN_BATCH_LIMIT ?= 25
MAX_BATCHES_PER_TICK ?= 8
FORECAST_UPLOAD_LIMIT ?= 250

.PHONY: build run-hourly run-once stop logs shell doctor test

build:
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

run-hourly:
	docker run -d \
		--name $(CONTAINER_NAME) \
		--restart unless-stopped \
		--env-file $(ENV_FILE) \
		-e RESEARCH_PROCESSING_ROOT=/app \
		-e STATE_DB_PATH=$(STATE_DB_PATH) \
		-e ANALYSIS_DB_URL=$(ANALYSIS_DB_URL) \
		-e POLL_INTERVAL_SECONDS=$(POLL_INTERVAL_SECONDS) \
		-e RUN_BATCH_LIMIT=$(RUN_BATCH_LIMIT) \
		-e MAX_BATCHES_PER_TICK=$(MAX_BATCHES_PER_TICK) \
		-e FORECAST_UPLOAD_LIMIT=$(FORECAST_UPLOAD_LIMIT) \
		-v $(HOST_STATE_DB_PATH):$(CONTAINER_STATE_DB_PATH):ro \
		-v $(HOST_ANALYSIS_DIR):$(CONTAINER_ANALYSIS_DIR) \
		-v $(HOST_PIPELINE_OPS_DIR):/app/research_pipeline_ops:ro \
		$(IMAGE_NAME):$(IMAGE_TAG)

run-once:
	docker run --rm \
		--env-file $(ENV_FILE) \
		-e RESEARCH_PROCESSING_ROOT=/app \
		-e STATE_DB_PATH=$(STATE_DB_PATH) \
		-e ANALYSIS_DB_URL=$(ANALYSIS_DB_URL) \
		-e RUN_BATCH_LIMIT=$(RUN_BATCH_LIMIT) \
		-v $(HOST_STATE_DB_PATH):$(CONTAINER_STATE_DB_PATH):ro \
		-v $(HOST_ANALYSIS_DIR):$(CONTAINER_ANALYSIS_DIR) \
		-v $(HOST_PIPELINE_OPS_DIR):/app/research_pipeline_ops:ro \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		python -m research_analysis_layer.main run --limit $(RUN_BATCH_LIMIT)

doctor:
	docker run --rm \
		--env-file $(ENV_FILE) \
		-e RESEARCH_PROCESSING_ROOT=/app \
		-e STATE_DB_PATH=$(STATE_DB_PATH) \
		-e ANALYSIS_DB_URL=$(ANALYSIS_DB_URL) \
		-v $(HOST_STATE_DB_PATH):$(CONTAINER_STATE_DB_PATH):ro \
		-v $(HOST_ANALYSIS_DIR):$(CONTAINER_ANALYSIS_DIR) \
		-v $(HOST_PIPELINE_OPS_DIR):/app/research_pipeline_ops:ro \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		python -m research_analysis_layer.main doctor

logs:
	docker logs -f $(CONTAINER_NAME)

shell:
	docker run --rm -it \
		--env-file $(ENV_FILE) \
		-e RESEARCH_PROCESSING_ROOT=/app \
		-e STATE_DB_PATH=$(STATE_DB_PATH) \
		-e ANALYSIS_DB_URL=$(ANALYSIS_DB_URL) \
		-v $(HOST_STATE_DB_PATH):$(CONTAINER_STATE_DB_PATH):ro \
		-v $(HOST_ANALYSIS_DIR):$(CONTAINER_ANALYSIS_DIR) \
		-v $(HOST_PIPELINE_OPS_DIR):/app/research_pipeline_ops:ro \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		/bin/sh

stop:
	-docker stop $(CONTAINER_NAME)
	-docker rm $(CONTAINER_NAME)

test:
	PYTHONPATH=src python3 -m unittest discover -s tests
