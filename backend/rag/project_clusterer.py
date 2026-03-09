import json
import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import normalize
from backend.db.chroma_client import get_documents_collection, get_projects_collection
from backend.ingestion.embedder import embed_texts
from backend.rag.llm_chain import generate_project_summary
from backend.db.models import SessionLocal, ProjectCluster, UploadRecord
from datetime import datetime

def run_project_clustering():
    """
    Main clustering pipeline:
    1. Fetch all document embeddings from ChromaDB
    2. DBSCAN cluster them by semantic similarity
    3. For each cluster, use LLM to infer a project name + description
    4. Save clusters to DB and ChromaDB projects collection
    """
    collection = get_documents_collection()
    all_data = collection.get(include=["embeddings", "metadatas", "documents"])

    if not all_data["ids"]:
        return []

    # Cluster Personal Schedule + Project Resources documents.
    # Schedules capture individual commitments; project resources add doc-level context.
    schedule_indices = [
        i for i, meta in enumerate(all_data["metadatas"])
        if meta.get("doc_category") in ("personal_schedule", "project_resources")
    ]
    if not schedule_indices:
        return []

    embeddings = np.array([all_data["embeddings"][i] for i in schedule_indices])
    metadatas  = [all_data["metadatas"][i]  for i in schedule_indices]
    documents  = [all_data["documents"][i]  for i in schedule_indices]

    # Normalize for cosine similarity
    embeddings_norm = normalize(embeddings)

    # DBSCAN: eps controls how tight a cluster is (lower = tighter)
    clustering = DBSCAN(eps=0.18, min_samples=2, metric="cosine").fit(embeddings_norm)
    labels = clustering.labels_

    cluster_map = {}
    for idx, label in enumerate(labels):
        if label == -1:
            continue  # noise / unclustered
        cluster_map.setdefault(label, []).append(idx)

    db = SessionLocal()
    # Clear old clusters
    db.query(ProjectCluster).delete()

    project_clusters = []
    for label, indices in cluster_map.items():
        # Gather sample chunks (max 6 for LLM prompt)
        sample_chunks = [documents[i] for i in indices[:6]]
        sample_meta = [metadatas[i] for i in indices]

        # Collect contributing users
        contributors = list({m.get("user_email", "") for m in sample_meta if m.get("user_email")})
        contributor_names = list({m.get("user_name", "") for m in sample_meta if m.get("user_name")})

        # Ask LLM to name and describe this project
        llm_result = generate_project_summary(sample_chunks, contributor_names)

        cluster_entry = ProjectCluster(
            name=llm_result["project_name"],
            description=llm_result["description"],
            keywords=json.dumps(llm_result["keywords"]),
            member_emails=json.dumps(contributors),
        )
        db.add(cluster_entry)

        # Update upload records with inferred project
        for i in indices:
            filename = metadatas[i].get("filename")
            user_email = metadatas[i].get("user_email")
            if filename and user_email:
                db.query(UploadRecord).filter(
                    UploadRecord.filename == filename
                ).update({"inferred_project": llm_result["project_name"]})

        project_clusters.append({
            "project_name": llm_result["project_name"],
            "description": llm_result["description"],
            "keywords": llm_result["keywords"],
            "contributors": contributor_names,
            "contributor_emails": contributors,
            "document_count": len(indices)
        })

    db.commit()
    db.close()
    return project_clusters