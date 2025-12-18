
import logging
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session
from backend.app.services.cost import CostService
from backend.app.db.models import DbAIModel, DbTokenUsage
from backend.app.core import config

def test_get_model_pricing_db_hit():
    """Test retrieving pricing from DB when it exists."""
    mock_session = MagicMock(spec=Session)
    mock_model = DbAIModel(id="gpt-mock", input_price_per_1m=1.0, output_price_per_1m=2.0)
    
    # Setup mock query
    mock_query = mock_session.query.return_value
    mock_query.filter.return_value.first.return_value = mock_model
    
    pricing = CostService.get_model_pricing(mock_session, "gpt-mock")
    assert pricing is not None
    assert pricing.input_price_per_1m == 1.0
    assert pricing.output_price_per_1m == 2.0

def test_track_usage_db_pricing():
    """Test tracking usage with pricing found in DB."""
    mock_session = MagicMock(spec=Session)
    mock_model = DbAIModel(id="gpt-mock", input_price_per_1m=10.0, output_price_per_1m=20.0) # Simple numbers
    
    mock_query = mock_session.query.return_value
    mock_query.filter.return_value.first.return_value = mock_model
    
    # 1M tokens input -> $10. 1M output -> $20.
    # We pass 500k input (0.5 * 10 = 5) and 500k output (0.5 * 20 = 10). Total 15.
    cost = CostService.track_usage(
        mock_session, 
        "gpt-mock", 
        prompt_tokens=500_000, 
        completion_tokens=500_000, 
        job_id="job-123"
    )
    
    assert cost == 15.0
    
    # Verify add() was called with correct DbTokenUsage object
    mock_session.add.assert_called_once()
    args, _ = mock_session.add.call_args
    usage_record = args[0]
    
    assert isinstance(usage_record, DbTokenUsage)
    assert usage_record.prompt_tokens == 500_000
    assert usage_record.completion_tokens == 500_000
    assert usage_record.total_tokens == 1_000_000
    assert usage_record.cost == 15.0
    assert usage_record.job_id == "job-123"
    assert usage_record.model_id == "gpt-mock"
    
    mock_session.commit.assert_called_once()

def test_track_usage_fallback_config():
    """Test tracking usage when DB pricing is missing, falling back to config."""
    mock_session = MagicMock(spec=Session)
    
    # DB returns None
    mock_query = mock_session.query.return_value
    mock_query.filter.return_value.first.return_value = None
    
    # Mock config
    with patch.dict(config.MODEL_PRICING, {"gpt-fallback": {"input": 5.0, "output": 5.0}}, clear=False):
        cost = CostService.track_usage(
            mock_session, 
            "gpt-fallback", 
            prompt_tokens=1_000_000, 
            completion_tokens=0
        )
        
        # 1M input * 5.0 = 5.0
        assert cost == 5.0
        
        # Should NOT save to DB if model doesn't exist in ai_models (to avoid FK error)
        # OR implementation decides to skip.
        # Check logic: "if pricing: session.add()... else: logger.error..."
        mock_session.add.assert_not_called()
