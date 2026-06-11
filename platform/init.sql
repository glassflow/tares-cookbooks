CREATE TABLE IF NOT EXISTS users (
    id    SERIAL PRIMARY KEY,
    name  TEXT,
    email TEXT
);

INSERT INTO users (name, email)
SELECT 'User ' || g, 'user' || g || '@example.com'
FROM generate_series(1, 200) AS g;
