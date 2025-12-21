import logging
import time
from typing import Optional

from sqlalchemy.orm import Session
from backend.app.db.models import DbAIModel, DbTokenUsage
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

class CostService:
    @staticmethod
    def get_model_pricing(session: Session, model_name: str) -> Optional[DbAIModel]:
        """
        Fetch pricing for a given model. 
        Tries to find exact match, then falls back to Config if DB entry missing (optional fallback strategy).
        """
        model = session.query(DbAIModel).filter(DbAIModel.id == model_name).first()
        return model

    @staticmethod
    def track_usage(
        session: Session, 
        model_name: str, 
        prompt_tokens: int, 
        completion_tokens: int,
        job_id: Optional[str] = None
    ) -> float:
        """
        Calculate cost, log it, and save to database.
        Returns the calculated cost in USD.
        """
        pricing = CostService.get_model_pricing(session, model_name)
        
        input_price = 0.0
        output_price = 0.0
        
        if pricing:
            input_price = pricing.input_price_per_1m
            output_price = pricing.output_price_per_1m
        else:
            # Fallback to Config or Default if DB missing (Safety net)
            # Though migration should have seeded it.
            logger.warning(f"Pricing not found in DB for model {model_name}. Using fallback.")
            # Fallback from settings
            model_pricing = settings.llm_pricing.get(model_name, {})
            input_price = model_pricing.get("input", settings.default_llm_input_price)
            output_price = model_pricing.get("output", settings.default_llm_output_price)

        input_cost = (prompt_tokens / 1_000_000) * input_price
        output_cost = (completion_tokens / 1_000_000) * output_price
        total_cost = input_cost + output_cost

        usage_record = DbTokenUsage(
            job_id=job_id,
            model_id=model_name if pricing else "unknown", # Or handle foreign key constraint if missing
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost=total_cost,
            timestamp=int(time.time())
        )
        
        # If pricing is missing from DB, we can't save 'model_id' if foreign key is strict.
        # But our migration seeded tables.
        # To be safe against crashes, we check if pricing exists before saving.
        if pricing:
            session.add(usage_record)
            try:
                session.commit()
            except Exception as e:
                logger.error(f"Failed to save token usage: {e}")
                session.rollback()
        else:
             logger.error(f"Skipping DB save for token usage: Model {model_name} not in ai_models table.")

        return total_cost
