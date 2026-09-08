import json
import boto3
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sqs = boto3.client("sqs")

QUEUE_URL = os.environ.get(
    "ORCHESTRATOR_QUEUE_URL",
    ""
)

def lambda_handler(event, context):

    logger.info("DATADOG WEBHOOK RECEIVED")
    logger.info(json.dumps(event))

    try:

        body = {}

        if event.get("body"):
            body = json.loads(event["body"])
            logger.info("RAW DATADOG BODY START")
            logger.info(json.dumps(body))
            logger.info("RAW DATADOG BODY END")

        TARGET_INSTANCE_ID = os.environ.get("TARGET_INSTANCE_ID", "")   
        logger.info(f"TARGET_INSTANCE_ID={TARGET_INSTANCE_ID}") 

        alert = {
            "alert_id": body.get("alert_id", "test"),
            "alert_name": body.get("event", "Datadog Alert"),
            "host": body.get("host", "unknown"),
            "instance_id": TARGET_INSTANCE_ID,
            "metric": body.get("metric", "cpu"),
            #"severity": "P2",
            "severity": body.get("severity", "P3"),
            "value": "80",
            "message": json.dumps(body)
        }
        
        logger.info("SQS PAYLOAD START")
        logger.info(json.dumps(alert))
        logger.info("SQS PAYLOAD END")

        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(alert)
        )

        logger.info("Message sent to SQS")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": "success"
            })
        }

    except Exception as e:

        logger.error(str(e))

        return {
            "statusCode": 500,
            "body": str(e)
        }