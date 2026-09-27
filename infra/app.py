"""CDK app. Synth needs no AWS credentials:

    cd infra && python app.py          # or: npx cdk synth

Deploying is a separate, deliberate step; see infra/README.md.
"""
import aws_cdk as cdk

from auralane_stack import REGION, AuralaneStack

app = cdk.App()
# Account left unresolved on purpose, so synth never looks anything up.
AuralaneStack(app, "Auralane", env=cdk.Environment(region=REGION),
              description="AURALane PoC: S3, DynamoDB, Cognito, HealthImaging import role, "
                          "chest Lambda, brain SageMaker async endpoint. Non-diagnostic.")
app.synth()
