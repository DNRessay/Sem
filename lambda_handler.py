"""
Light-tier entrypoint. Wraps the FastAPI app for AWS Lambda via a Function URL
(not API Gateway — Function URLs have no request charge and no 12-month free
tier cliff, so this stays free at low volume indefinitely).
"""
from mangum import Mangum

from main import app

handler = Mangum(app, lifespan="auto")
