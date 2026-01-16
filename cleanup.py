import os
from datetime import datetime
import pymysql.cursors

def format_api_version(version: str) -> str:
    """Convert version string to XXX.YYY.ZZZ format for comparison."""
    version_parts = version.split('.')
    return f"{int(version_parts[0]):03d}.{int(version_parts[1]):03d}.{int(version_parts[2]):03d}"

def cleanup_anonymized_queries_collection(anonymizedqueries, strapiversion: str):
    """Cleanup the anonymized queries collection stored as embeddings in ChromaDB."""
    print(f"Starting cleanup of anonymized queries cache...")
    print(f"Current API version: {strapiversion}")
    print(f"Formatted current version: {format_api_version(strapiversion)}")
    
    try:
        # Fix to delete all query with id bb7f97e70d9481e0fc67d3b72508fd3fa78f939f06e8bdd1a8a533c37cda8461
        stridtodelete = "bb7f97e70d9481e0fc67d3b72508fd3fa78f939f06e8bdd1a8a533c37cda8461"
        print("Fix to delete all query with id", stridtodelete)
        batch_size = 1000
        offset = 0
        while True:
            # Step 1: get all ids matching bb7f97e70d9481e0fc67d3b72508fd3fa78f939f06e8bdd1a8a533c37cda8461
            results = anonymizedqueries.get(include=[], limit=batch_size, offset=offset)
            ids = results["ids"]
            #print(results["ids"])
            if not ids:
                break
            ids_to_delete = [r for r in ids if r.startswith(stridtodelete)]
            print("offset", offset, "ids_to_delete", ids_to_delete)
            if ids_to_delete:
                anonymizedqueries.delete(ids=ids_to_delete)
                print(f"Deleted {len(ids_to_delete)} docs with prefix {stridtodelete}")

            if len(ids) < batch_size:
                break
            offset += batch_size

        # Get all documents from the collection
        print("Retrieving all documents from the collection...")
        all_docs = anonymizedqueries.get(include=['metadatas'])
        
        if not all_docs['ids']:
            print("No documents found in the collection.")
            return
        
        print(f"Found {len(all_docs['ids'])} documents in the collection")
        
        # Find documents with older API versions
        docs_to_delete = []
        current_version_formatted = format_api_version(strapiversion)
        
        for i, doc_id in enumerate(all_docs['ids']):
            metadata = all_docs['metadatas'][i]
            
            docs_to_delete.append({
                'id': doc_id,
                'created': metadata.get('dat_creat', 'Unknown')
            })
            print(f"Marked for deletion: ID={doc_id[:8]}..., Created={metadata.get('dat_creat', 'Unknown')}")
        
        if not docs_to_delete:
            print("No old documents found. All documents are current.")
            return
        
        print(f"\nFound {len(docs_to_delete)} documents to delete:")
        for doc in docs_to_delete:
            print(f"  - ID: {doc['id'][:8]}..., Created: {doc['created']}")
        
        # Confirm deletion
        #response = input(f"\nDo you want to delete these {len(docs_to_delete)} documents? (y/N): ")
        response = "y"
        if response.lower() != 'y':
            print("Deletion cancelled.")
            return
        
        # Delete the documents
        print("Deleting old documents...")
        ids_to_delete = [doc['id'] for doc in docs_to_delete]
        
        # ChromaDB delete method expects a list of IDs
        anonymizedqueries.delete(ids=ids_to_delete)
        
        print(f"Successfully deleted {len(docs_to_delete)} old documents from the anonymizedqueries collection.")
        
        # Verify deletion
        remaining_docs = anonymizedqueries.get(include=['metadatas'])
        print(f"Remaining documents in collection: {len(remaining_docs['ids'])}")
        
    except Exception as e:
        print(f"Error during cleanup: {str(e)}")
        raise

def cleanup_sql_cache(connection, strapiversion: str):
    """Cleanup the SQL cache stored as a table in MariaDB."""
    print(f"Starting cleanup of SQL cache...")
    print(f"Current API version: {strapiversion}")
    startpiversionformatted = format_api_version(strapiversion)
    strsql="DELETE FROM T_WC_T2S_CACHE WHERE API_VERSION = %s"
    connection.cursor().execute(strsql, (startpiversionformatted,))
    connection.commit()
    print(f"Successfully deleted {connection.cursor().rowcount} rows from the SQL cache.")
