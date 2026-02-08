#!/bin/bash

# Check if the text2sql-eval Docker container is running
if [ $(docker ps -q -f name=text2sql-eval) ]; then
    echo "text2sql-eval Docker container is already running."
else
    # Start the text2sql-eval container if it is not running
    cd $HOME/docker/text2sql-eval
    docker build -t text2sql-eval-python-app .
    # docker run -it --rm --network="host" --name text2sql-eval text2sql-eval-python-app
    docker run -d --rm --network="host" --name text2sql-eval text2sql-eval-python-app
    echo "text2sql-eval Docker container started."
fi
