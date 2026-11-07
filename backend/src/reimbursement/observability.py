import json
import logging


class JSONFormatter(logging.Formatter):
    def format(self, record):
        data = {"level": record.levelname, "event": record.getMessage()}
        for key in (
            "request_id",
            "workspace_id",
            "claim_id",
            "run_id",
            "job_id",
            "attempt_id",
            "error_type",
            "status",
            "elapsed_ms",
        ):
            value = getattr(record, key, None)
            if value is not None:
                data[key] = value
        return json.dumps(data, ensure_ascii=False)


def configure_logging():
    logger = logging.getLogger("reimbursement")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
