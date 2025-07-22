#!/usr/bin/env python3
"""
A minimal script to simulate using the Relia application in small, memory-friendly chunks.
"""

import logging
import json
import time
from pathlib import Path
from uuid import uuid4

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ensure required directories exist
data_dir = Path('.relia-data')
data_dir.mkdir(exist_ok=True)
playbooks_dir = Path('.relia-playbooks')
playbooks_dir.mkdir(exist_ok=True)

# Simulate database operations with a JSON file
db_file = data_dir / 'simulated_db.json'
if not db_file.exists():
    with open(db_file, 'w') as f:
        json.dump({
            'playbooks': [],
            'telemetry': [],
            'feedback': []
        }, f, indent=2)

def load_db():
    try:
        with open(db_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading DB: {e}")
        return {'playbooks': [], 'telemetry': [], 'feedback': []}

def save_db(data):
    try:
        with open(db_file, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving DB: {e}")

def simulate_generate_playbook(module_name, prompt):
    """Simulate generating a playbook."""
    logger.info(f"Generating playbook for module: {module_name}, prompt: {prompt}")
    
    # Simulate LLM processing delay
    time.sleep(0.5)
    
    # Create a unique ID for the playbook
    playbook_id = str(uuid4())
    
    # Create a simple YAML playbook
    yaml_content = f"---\n- name: Simulated playbook for {module_name}\n  hosts: all\n  tasks:\n  - name: {prompt}\n    {module_name}:\n      path: /tmp/example\n      state: present\n"
    
    # Save the playbook to disk
    playbook_path = playbooks_dir / f"{playbook_id}.yml"
    with open(playbook_path, 'w') as f:
        f.write(yaml_content)
    
    # Record in DB
    db = load_db()
    db['playbooks'].append({
        'id': playbook_id,
        'module': module_name,
        'prompt': prompt,
        'created_at': time.time(),
        'status': 'generated'
    })
    save_db(db)
    
    logger.info(f"Generated playbook {playbook_id}")
    return playbook_id, yaml_content

def simulate_lint_playbook(playbook_id):
    """Simulate linting a playbook."""
    logger.info(f"Linting playbook: {playbook_id}")
    
    # Simulate processing delay
    time.sleep(0.3)
    
    # Check if the playbook exists
    playbook_path = playbooks_dir / f"{playbook_id}.yml"
    if not playbook_path.exists():
        logger.error(f"Playbook {playbook_id} not found")
        return ["Playbook not found"]
    
    # Simulate linting results
    errors = []
    if len(str(playbook_id)) % 2 == 0:  # Randomly add an error based on ID
        errors.append("yaml[indentation]: Too many spaces before comment")
    
    # Update DB
    db = load_db()
    for playbook in db['playbooks']:
        if playbook['id'] == playbook_id:
            playbook['status'] = 'linted'
            playbook['lint_errors'] = errors
            break
    save_db(db)
    
    logger.info(f"Linted playbook {playbook_id} with {len(errors)} errors")
    return errors

def simulate_test_playbook(playbook_id):
    """Simulate testing a playbook."""
    logger.info(f"Testing playbook: {playbook_id}")
    
    # Simulate processing delay
    time.sleep(0.7)
    
    # Check if the playbook exists
    playbook_path = playbooks_dir / f"{playbook_id}.yml"
    if not playbook_path.exists():
        logger.error(f"Playbook {playbook_id} not found")
        return "failed", "Playbook not found"
    
    # Simulate test results (pass/fail based on playbook_id characters)
    status = "passed" if sum(ord(c) for c in playbook_id) % 3 != 0 else "failed"
    logs = f"Started molecule test\nRunning scenario 'default'\nVerifying playbook syntax...\nApplying playbook...\nTest {'succeeded' if status == 'passed' else 'failed'}\n"
    
    # Update DB
    db = load_db()
    for playbook in db['playbooks']:
        if playbook['id'] == playbook_id:
            playbook['status'] = f"tested_{status}"
            playbook['test_logs'] = logs
            break
    save_db(db)
    
    logger.info(f"Tested playbook {playbook_id}: {status}")
    return status, logs

def record_feedback(playbook_id, rating, comment=None):
    """Simulate recording feedback for a playbook."""
    logger.info(f"Recording feedback for playbook {playbook_id}: rating={rating}, comment={comment}")
    
    # Check if the playbook exists
    playbook_path = playbooks_dir / f"{playbook_id}.yml"
    if not playbook_path.exists():
        logger.error(f"Playbook {playbook_id} not found")
        return False
    
    # Record feedback in DB
    db = load_db()
    feedback_id = str(uuid4())
    db['feedback'].append({
        'id': feedback_id,
        'playbook_id': playbook_id,
        'rating': rating,
        'comment': comment,
        'created_at': time.time()
    })
    save_db(db)
    
    logger.info(f"Recorded feedback {feedback_id}")
    return True

def run_simulation_in_chunks(chunk_size=5, total_runs=20):
    """Run the simulation in smaller chunks to avoid memory issues."""
    modules = ['ansible.builtin.file', 'ansible.builtin.copy', 'ansible.builtin.service', 
               'ansible.builtin.user', 'ansible.builtin.package']
    prompts = [
        "Create a configuration file",
        "Restart the web service",
        "Create a new user account",
        "Install required packages",
        "Set file permissions"
    ]
    
    for chunk_num in range(0, total_runs, chunk_size):
        logger.info(f"\n\n--- Running simulation chunk {chunk_num//chunk_size + 1}/{total_runs//chunk_size} ---")
        
        # Only process chunk_size items in this chunk
        for i in range(chunk_num, min(chunk_num + chunk_size, total_runs)):
            # Select module and prompt (cycling through available options)
            module = modules[i % len(modules)]
            prompt = prompts[i % len(prompts)]
            
            # Generate a playbook
            playbook_id, _ = simulate_generate_playbook(module, prompt)
            
            # Lint the playbook
            lint_errors = simulate_lint_playbook(playbook_id)
            
            # Test the playbook
            status, _ = simulate_test_playbook(playbook_id)
            
            # Record feedback
            rating = 5 if not lint_errors and status == "passed" else 3
            record_feedback(playbook_id, rating, "Generated as expected")
            
            # Clean up memory
            del lint_errors, status
        
        # Force garbage collection at the end of each chunk
        import gc
        gc.collect()
        
        # Add a small delay between chunks
        logger.info(f"Completed chunk {chunk_num//chunk_size + 1}, sleeping before next chunk...")
        time.sleep(1)

def main():
    """Main entry point for the simulation."""
    logger.info("Starting Relia App simulation in small chunks")
    
    # Set small chunk size to avoid memory issues
    run_simulation_in_chunks(chunk_size=2, total_runs=10)
    
    logger.info("Simulation complete")
    
    # Show summary statistics
    db = load_db()
    logger.info("\nSimulation results:\n")
    logger.info(f"  Total playbooks: {len(db['playbooks'])}")
    logger.info(f"  Total feedback entries: {len(db['feedback'])}")
    
    # Calculate average rating
    ratings = [f['rating'] for f in db['feedback']]
    avg_rating = sum(ratings) / len(ratings) if ratings else 0
    logger.info(f"  Average feedback rating: {avg_rating:.1f}")

if __name__ == "__main__":
    main()
