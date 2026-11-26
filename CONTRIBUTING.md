# Contributing to Ribhus

Thank you for your interest in contributing to Ribhus.

## Getting Started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/Ribhus.git
   cd Ribhus
   ```
3. Set up the development environment:
   ```bash
   cp .env.example .env
   uv sync --extra dev
   uv run playwright install chromium
   ```
4. Create a feature branch:
   ```bash
   git checkout -b feat/your-feature
   ```

## Development Workflow

### Running Tests

```bash
uv run pytest
```

### Running the Eval Suite

```bash
uv run ribhus eval
uv run ribhus eval --category safety
uv run ribhus eval --json
```

The eval suite uses mocked fixtures and does not require API keys or logged-in channels.

### Code Style

- Follow existing code patterns
- Use type hints
- Keep functions focused and testable

## Pull Request Process

1. Ensure tests pass locally
2. Write clear commit messages
3. Update documentation if needed
4. Open a pull request with a clear description of the change

## Areas for Contribution

- **Tools**: New built-in tools or improvements to existing ones
- **Skills**: New skill packages in `skills/`
- **Channels**: New messaging channels or channel improvements
- **Documentation**: Guides, examples, and API documentation
- **Tests**: Expanding test coverage
- **Dashboard**: UI improvements in `web/`

## Skill Contributions

To contribute a skill:

1. Create a skill directory:
   ```bash
   uv run ribhus skill create my-skill
   ```
2. Edit the generated files in `skills/my-skill/`
3. Validate your skill:
   ```bash
   uv run ribhus skill validate ./skills/my-skill
   ```
4. Submit a PR with the skill directory

See [docs/skills.md](docs/skills.md) for the skill format specification.

## Questions

Open an issue for questions, bug reports, or feature requests.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
