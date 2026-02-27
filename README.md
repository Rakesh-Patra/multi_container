# Docker DevOps Agent

An intelligent, conversational DevOps assistant powered by the Strands Agents SDK and Gemini. This agent acts as a Senior DevOps Engineer with 10+ years of experience, managing your production infrastructure, Docker containers, and docker-compose configurations.

## Features

- **Conversational CLI**: Rich interactive REPL with memory persistence across sessions.
- **Docker Management**: List, inspect, and monitor running containers and their stats.
- **Compose Lifecycle**: Validate, deploy (`up`), tear down (`down`), diff, and generate `docker-compose.yml` files safely.
- **Intelligent Monitoring**: Detect port conflicts, check disk usage, and safely prune unused Docker resources.
- **Automated Testing**: Features an 8-point post-deployment test suite that automatically validates the health, connectivity, and volume mounts after every deployment.
- **Safe by Default**: Automatically backs up configurations before making destructive changes. Enforces strict exception handling and logging workflows.

## Prerequisites

- Python 3.11+
- Docker (The agent requires access to the Docker daemon to execute commands)
- Google Gemini API Key

## Setup & Installation

### Local Setup

1. **Clone the repository** and navigate into the directory:
   ```bash
   cd mult_container
   ```

2. **Create a virtual environment and install dependencies:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Environment Setup:**
   Create a `.env` file in the project root containing your Gemini API key:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   ```

4. **Run the Agent:**
   ```bash
   python main.py
   ```

### Docker Setup

You can deploy the agent as a Docker container itself. Note that you must mount the host's Docker socket so the agent can manage the host's infrastructure.

1. **Build the image:**
   ```bash
   docker build -t docker-devops-agent .
   ```

2. **Run the container interactively:**
   ```bash
   docker run -it \
     -v /var/run/docker.sock:/var/run/docker.sock \
     -v $(pwd)/compose_files:/app/compose_files \
     -v $(pwd)/backups:/app/backups \
     -v $(pwd)/logs:/app/logs \
     --env-file .env \
     docker-devops-agent
   ```

## Workflows & Tools

The agent utilizes a suite of over 20 integrated tools located in the `tools/` directory:
- **`compose_tools.py`**: Generation, validation, diffing, and execution of Docker Compose files.
- **`docker_tools.py`**: Container inspections, logs fetching, and detailed health checks.
- **`monitoring_tools.py`**: Port availability, conflict detection, and system pruning.
- **`testing_tools.py`**: Post-deployment 8-point checklist execution.
- **`image_tools.py`**: Pulling, removing, and analyzing images/Dockerfiles.

## Logging

All agent operations, reasoning, and test results are rigorously logged to the `logs/` directory for full traceability. Past conversation sessions are persisted to `logs/sessions/`.
