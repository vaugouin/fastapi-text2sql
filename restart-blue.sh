docker ps --filter "name=fastapi-text2sql-blue"

docker stop fastapi-text2sql-blue 

cd /home/debian/docker/fastapi-text2sql
clear
docker build -t fastapi-text2sql-blue-app .
#docker run -it --rm --network="host" -v $(pwd):/app --name fastapi-text2sql-blue fastapi-text2sql-blue-app
docker run -d --rm --network="host" -v $(pwd):/app --name fastapi-text2sql-blue fastapi-text2sql-blue-app

docker ps --filter "name=fastapi-text2sql-blue"

