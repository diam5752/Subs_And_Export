UPDATE ai_models
SET active = FALSE
WHERE id LIKE 'gpt-%';

DELETE FROM ai_models AS model
WHERE model.id LIKE 'gpt-%'
  AND NOT EXISTS (
      SELECT 1
      FROM token_usage AS usage
      WHERE usage.model_id = model.id
  );
