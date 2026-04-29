"""
utils/ml_matching.py
--------------------
TF-IDF based semantic freelancer matching.

How TF-IDF works (simple version):
  - TF  (Term Frequency)  = how often a word appears in a document
  - IDF (Inverse Document Frequency) = how rare that word is across ALL documents
  - TF-IDF score = TF * IDF → rare words that appear a lot in one doc get high scores
  - cosine_similarity then measures the "angle" between two score vectors
    → 1.0 = identical meaning, 0.0 = nothing in common

Why this beats exact keyword matching:
  - "API development" matches "REST endpoints" via shared vocabulary context
  - "build scalable services" matches "backend engineering" semantically
  - Works on full sentences, not just comma-separated skill tags
"""

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def ml_match_freelancers(job: dict, freelancers: list[dict]) -> list[dict]:
    """
    Computes TF-IDF cosine similarity between a job posting and each freelancer profile.

    Args:
        job         : dict with keys 'title', 'description', 'skills_required'
        freelancers : list of dicts, each with 'id', 'username', 'full_name', 'skills', 'bio'

    Returns:
        List of dicts sorted by ml_score descending:
        [
            {
                "id":       int,
                "username": str,
                "full_name": str,
                "ml_score": int,   # 0–100 percentage
                "skills":   str,
            },
            ...
        ]
        Only freelancers with ml_score > 0 are included.
    """
    if not freelancers:
        return []

    # Build the job's text corpus — combine title + description + required skills
    # More weight to skills by repeating them (simple boosting trick)
    job_text = (
        f"{job.get('title', '')} "
        f"{job.get('description', '')} "
        f"{job.get('skills_required', '')} "
        f"{job.get('skills_required', '')}"  # repeated to boost skill weight
    ).strip()

    if not job_text:
        return []

    # Build each freelancer's text corpus — skills + bio
    # Skills repeated for same boosting reason
    freelancer_texts = []
    valid_freelancers = []

    for fl in freelancers:
        skills = fl.get("skills") or ""
        bio    = fl.get("bio") or ""
        text   = f"{skills} {skills} {bio}".strip()

        if not text:
            continue

        freelancer_texts.append(text)
        valid_freelancers.append(fl)

    if not freelancer_texts:
        return []

    # Combine into one corpus: job first, then all freelancers
    # TfidfVectorizer learns vocabulary from ALL documents together
    all_texts = [job_text] + freelancer_texts

    vectorizer = TfidfVectorizer(
        stop_words="english",   # ignore common words like "the", "and", "is"
        ngram_range=(1, 2),     # use single words AND 2-word phrases ("react native", "rest api")
        min_df=1,               # include terms that appear at least once
        sublinear_tf=True,      # apply log normalization to term frequency
    )

    # Fit and transform all texts into TF-IDF matrix
    tfidf_matrix = vectorizer.fit_transform(all_texts)

    # Job vector is row 0, freelancer vectors are rows 1..N
    job_vector          = tfidf_matrix[0]
    freelancer_vectors  = tfidf_matrix[1:]

    # Compute cosine similarity between job and every freelancer
    # Result shape: (1, N) — one similarity score per freelancer
    similarities = cosine_similarity(job_vector, freelancer_vectors)[0]

    # Build results, converting raw similarity (0.0–1.0) to percentage (0–100)
    results = []
    for i, fl in enumerate(valid_freelancers):
        score = round(float(similarities[i]) * 100)
        if score == 0:
            continue  # skip completely irrelevant profiles

        results.append({
            "id":        fl["id"],
            "username":  fl["username"],
            "full_name": fl.get("full_name") or fl["username"],
            "skills":    fl.get("skills") or "",
            "bio":       fl.get("bio") or "",
            "ml_score":  score,
        })

    # Sort by ml_score descending
    results.sort(key=lambda x: -x["ml_score"])
    return results
