-- Runs only on first container init (docker-entrypoint-initdb.d). Keeps the test
-- suite's create_all/drop_all away from the dev database ("dispatch").
CREATE DATABASE dispatch_test;
