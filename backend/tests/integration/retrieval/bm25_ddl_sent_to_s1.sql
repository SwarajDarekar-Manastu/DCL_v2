CREATE INDEX bm25_document_nodes ON document_nodes USING bm25 (
    node_id,
    (content::pdb.icu),
    (content::pdb.simple('stemmer=english', 'alias=content_stem_en')),
    (content::pdb.simple('stemmer=german', 'alias=content_stem_de')),
    (content::pdb.simple('stemmer=french', 'alias=content_stem_fr')),
    (content::pdb.simple('stemmer=spanish', 'alias=content_stem_es')),
    (content::pdb.simple('stemmer=italian', 'alias=content_stem_it')),
    (content::pdb.simple('stemmer=russian', 'alias=content_stem_ru')),
    (content::pdb.lindera('japanese', 'alias=content_ja')),
    (content::pdb.lindera('korean', 'alias=content_ko')),
    (content::pdb.jieba('alias=content_zh')),
    (content_codes::pdb.whitespace),
    (content_en::pdb.simple('stemmer=english')),
    (breadcrumb::pdb.simple('stemmer=english')),
    (node_type::pdb.literal),
    (doc_kind::pdb.literal),
    (test_plan_id::pdb.literal),
    (source_origin::pdb.literal),
    (doc_status::pdb.literal),
    (language::pdb.literal),
    doc_id,
    trust_tier,
    needs_review
);
CREATE INDEX bm25_documents ON documents USING bm25 (
    doc_id,
    (search_text::pdb.simple('stemmer=english')),
    (title::pdb.simple('stemmer=english')),
    (status::pdb.literal)
);
