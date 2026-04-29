-- Create a separate database for the pytest suite. Runs once when the
-- volume is initialised — drop the volume to re-trigger.
CREATE DATABASE auction_test;
GRANT ALL PRIVILEGES ON DATABASE auction_test TO auction;
