#!/bin/bash

# Check if the text2sql-eval Docker container is running
if [ $(docker ps -q -f name=text2sql-eval) ]; then
    echo "text2sql-eval Docker container is already running."
else
    # Start the text2sql-eval container if it is not running
    cd $HOME/docker/text2sql-eval
    docker build -t text2sql-eval-python-app .
    # Secrets are injected at runtime via --env-file from a host-managed env file
    # kept outside the app source tree (never baked into the image).
    # docker run -it --rm --network="host" --env-file /home/debian/docker/text2sql-eval/.env --name text2sql-eval -v /home/debian/docker/shared_data/text2sql-eval:/shared text2sql-eval-python-app --entity-extraction-model gpt-4o --text2sql-model gpt-4o --complex-model gpt-4o --api-version 1.1.16 --language "*" --no-store-to-cache --no-complex-model-used
    docker run -d --rm --network="host" --env-file /home/debian/docker/text2sql-eval/.env --name text2sql-eval -v /home/debian/docker/shared_data/text2sql-eval:/shared text2sql-eval-python-app --entity-extraction-model gpt-4o --text2sql-model gpt-4o --complex-model gpt-4o --api-version 1.1.16 --language "*" --no-store-to-cache --no-complex-model-used
    #docker run -d --rm --network="host" --env-file /home/debian/docker/text2sql-eval/.env --name text2sql-eval -v /home/debian/docker/shared_data/text2sql-eval:/shared text2sql-eval-python-app --entity-extraction-model gemma-4-google --text2sql-model gemma-4-google --complex-model gpt-4o --api-version 1.1.16 --language "*" --no-store-to-cache --no-complex-model-used
    #echo "text2sql-eval Docker container started."
    docker logs -f text2sql-eval
fi
