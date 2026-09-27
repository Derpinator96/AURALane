"""AWS providers, one per port. core/run.py builds them from the environment
(AURALANE_RUNTIME=aws); nothing else imports them.

  BlobPort       S3Blob                     core/providers/aws/s3.py
  TablePort      DynamoTable                core/providers/aws/dynamo.py (shares _dynamodb.py)
  DatastorePort  HealthImagingDatastore     core/providers/aws/healthimaging.py
  AuthPort       CognitoAuth                core/providers/aws/cognito.py
  InferencePort  LambdaSageMakerInference   core/providers/aws/inference.py
  LLMPort        BedrockLLM                 stub, deliberately

BedrockLLM stays a stub. Bedrock is blocked at the account level, and on
2026-09-25 the team decided drafting ships on TemplateLLM; no support case
will be opened before the presentation. It raises NotImplementedError naming
the service, so switching is a code and config change if access arrives.

No AWS SDK is imported anywhere outside this package.
"""
from core.ports import LLMPort
from core.providers.aws.cognito import CognitoAuth
from core.providers.aws.dynamo import DynamoTable
from core.providers.aws.healthimaging import HealthImagingDatastore
from core.providers.aws.inference import LambdaSageMakerInference
from core.providers.aws.s3 import S3Blob


def _todo(service):
    def method(self, *a, **k):
        raise NotImplementedError(f"{service}: not wired (Bedrock is blocked at the account "
                                  f"level; drafting runs on TemplateLLM)")
    return method


class BedrockLLM(LLMPort):
    draft = _todo("Amazon Bedrock InvokeModel")


__all__ = ["S3Blob", "DynamoTable", "HealthImagingDatastore", "CognitoAuth",
           "LambdaSageMakerInference", "BedrockLLM"]
