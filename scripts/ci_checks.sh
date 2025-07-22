#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Running CI checks for Relia...${NC}"

# Check Python version
echo -e "\n${YELLOW}Checking Python version...${NC}"
python --version
if [[ $(python -c 'import sys; print(sys.version_info >= (3, 10))') == 'False' ]]; then
    echo -e "${RED}Python 3.10 or higher is required${NC}"
    exit 1
fi
echo -e "${GREEN}Python version check passed${NC}"

# Check if poetry is installed
echo -e "\n${YELLOW}Checking Poetry installation...${NC}"
if ! command -v poetry &> /dev/null; then
    echo -e "${RED}Poetry is not installed. Please install it:${NC}"
    echo "curl -sSL https://install.python-poetry.org | python3 -"
    exit 1
fi
echo -e "${GREEN}Poetry installation check passed${NC}"

# Install dependencies
echo -e "\n${YELLOW}Installing Python dependencies...${NC}"
poetry install --with dev
echo -e "${GREEN}Dependencies installed${NC}"

# Run Python linting
echo -e "\n${YELLOW}Running Python linting...${NC}"
poetry run ruff check .
echo -e "${GREEN}Python linting passed${NC}"

# Run Python tests
echo -e "\n${YELLOW}Running Python tests...${NC}"
poetry run pytest
echo -e "${GREEN}Python tests passed${NC}"

# Check if Node.js is installed
echo -e "\n${YELLOW}Checking Node.js installation...${NC}"
if ! command -v node &> /dev/null; then
    echo -e "${YELLOW}Node.js is not installed. Skipping TypeScript checks${NC}"
else
    echo -e "${GREEN}Node.js installation check passed${NC}"
    
    # Run TypeScript checks
    echo -e "\n${YELLOW}Running TypeScript checks...${NC}"
    if [ -d "extension" ]; then
        cd extension
        npm ci
        npm run typecheck
        npm run compile
        cd ..
        echo -e "${GREEN}TypeScript checks passed${NC}"
    else
        echo -e "${YELLOW}No extension directory found. Skipping TypeScript checks${NC}"
    fi
fi

# Check Docker
echo -e "\n${YELLOW}Checking Docker installation...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}Docker is not installed. Skipping Docker build${NC}"
else
    echo -e "${GREEN}Docker installation check passed${NC}"
    
    # Build Docker image
    echo -e "\n${YELLOW}Building Docker image...${NC}"
    docker build -t relia:test .
    echo -e "${GREEN}Docker build passed${NC}"
fi

echo -e "\n${GREEN}All CI checks passed!${NC}"