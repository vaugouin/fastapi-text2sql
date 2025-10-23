docker ps --filter "name=fastapi-text2sql-green"

docker stop fastapi-text2sql-green

cd /home/debian/docker/fastapi-text2sql
clear
docker build -t fastapi-text2sql-green-app .
#docker run -it --rm --network="host" -v $(pwd):/app --name fastapi-text2sql-green fastapi-text2sql-green-app
docker run -d --rm --network="host" -v $(pwd):/app --name fastapi-text2sql-green fastapi-text2sql-green-app
# -p 8187:8000 

docker ps --filter "name=fastapi-text2sql-green"

