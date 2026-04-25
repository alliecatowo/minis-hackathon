#!/usr/bin/env python3
import os
import sys
import httpx
import argparse

def create_neon_branch(project_id, api_key, branch_name):
    url = f"https://console.neon.tech/api/v2/projects/{project_id}/branches"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    
    payload = {
        "branch": {
            "name": branch_name,
        },
        "endpoints": [
            {
                "type": "read_write",
            }
        ]
    }
    
    print(f"Creating Neon branch: {branch_name}...")
    with httpx.Client() as client:
        response = client.post(url, headers=headers, json=payload)

        if response.status_code in (409, 422):
            # 409: branch already exists
            # 422: API currently returns this for some duplicate-name conflicts.
            # Treat both as an idempotent "already exists" signal so reruns of
            # this workflow remain stable.
            if response.status_code == 422:
                try:
                    error_text = response.json().get("message", "")
                    if "already exists" not in error_text.lower():
                        response.raise_for_status()
                except Exception:
                    response.raise_for_status()

            print(f"Branch {branch_name} already exists. Fetching details...")
            # If it already exists, we might need to find it and get its connection string
            # For simplicity in this script, we'll try to list branches and find it
            list_url = f"https://console.neon.tech/api/v2/projects/{project_id}/branches"
            list_resp = client.get(list_url, headers=headers)
            list_resp.raise_for_status()
            branches = list_resp.json().get("branches", [])
            branch = next((b for b in branches if b["name"] == branch_name), None)
            if not branch:
                print(f"Error: Branch {branch_name} not found after 409 conflict.")
                sys.exit(1)
        else:
            response.raise_for_status()
            branch = response.json().get("branch")

        branch_id = branch["id"]
        print(f"Branch created/found: {branch_id}")

        # Wait for endpoint to be ready and get connection string
        # The creation response with endpoints might already have what we need
        # Some API responses include 'connection_uri' in the endpoint object
        endpoints = response.json().get("endpoints", []) if response.status_code != 409 else []
        
        if not endpoints:
            print("Fetching endpoints...")
            ep_url = f"https://console.neon.tech/api/v2/projects/{project_id}/endpoints"
            ep_resp = client.get(ep_url, headers=headers)
            ep_resp.raise_for_status()
            all_endpoints = ep_resp.json().get("endpoints", [])
            endpoints = [ep for ep in all_endpoints if ep["branch_id"] == branch_id]

        if not endpoints:
            print("No endpoint found for branch. Creating one...")
            ep_url = f"https://console.neon.tech/api/v2/projects/{project_id}/endpoints"
            ep_payload = {
                "endpoint": {
                    "branch_id": branch_id,
                    "type": "read_write",
                }
            }
            ep_resp = client.post(ep_url, headers=headers, json=ep_payload)
            ep_resp.raise_for_status()
            endpoint = ep_resp.json().get("endpoint")
        else:
            endpoint = endpoints[0]

        # Try to get connection string from API first
        db_user = os.environ.get("NEON_DB_USER", "neondb_owner")
        db_name = os.environ.get("NEON_DB_NAME", "neondb")
        db_pass = os.environ.get("NEON_DB_PASSWORD", "")

        # Use host from endpoint
        host = endpoint.get("host")
        
        # If the API provided a connection_uri in the endpoint, use it
        # Note: Neon API sometimes provides this if requested or available
        db_url = endpoint.get("connection_uri")
        
        if not db_url:
            if db_pass:
                db_url = f"postgresql://{db_user}:{db_pass}@{host}/{db_name}?sslmode=require"
            else:
                db_url = f"postgresql://{db_user}@{host}/{db_name}?sslmode=require"
        
        print(f"DATABASE_URL={db_url}")
        return db_url

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup Neon DB branch for PR")
    parser.add_argument("branch_name", help="Name of the branch to create")
    args = parser.parse_args()

    project_id = os.environ.get("NEON_PROJECT_ID")
    api_key = os.environ.get("NEON_API_KEY")

    if not project_id or not api_key:
        print("Error: NEON_PROJECT_ID and NEON_API_KEY environment variables are required.")
        sys.exit(1)

    try:
        db_url = create_neon_branch(project_id, api_key, args.branch_name)
        # Final output for the GitHub Action to capture
        if "GITHUB_OUTPUT" in os.environ:
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"db_url={db_url}\n")
        print(f"DATABASE_URL={db_url}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
