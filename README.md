# Subs_And_Export

Utilities for normalizing vertical videos and generating burned-in Greek subtitles.

## Continuous Integration / Continuous Deployment

This repository includes a lightweight GitHub Actions workflow at `.github/workflows/ci.yml` that runs the automated test suite on every push or pull request.

### How to enable CI/CD

1. Ensure your repository is hosted on GitHub.
2. Push the `.github/workflows/ci.yml` file to your default branch (e.g., `main`). GitHub Actions will automatically discover and run it on subsequent pushes and pull requests.
3. The workflow installs Python 3.12, upgrades `pip`, installs dependencies from `requirements.txt`, and runs `pytest`.
4. Check the Actions tab in GitHub to monitor runs and review logs.

### Local validation

Before pushing changes, you can run the same checks locally:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
pytest
```

Keeping local checks passing will help the CI workflow succeed.
