
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path.cwd()))

from pulldb.auth.password import verify_password

password = "PullDB_Dev2025!"
hash_val = "$2b$12$yBnagsAYiWx2reL6Zu/wJezUnOhmVpOM7E6k2m6VfICYxvksQHYOK"

print(f"Verifying password '{password}' against hash '{hash_val}'...")
result = verify_password(password, hash_val)
print(f"Result: {result}")
