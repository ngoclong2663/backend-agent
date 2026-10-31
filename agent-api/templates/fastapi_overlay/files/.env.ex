PORT=8000
DB_URL=postgresql://app:app@localhost:5432/app
# Dedicated database for pytest (will be truncated between tests)
TEST_DB_URL=postgresql://app:app@localhost:5432/app_test
