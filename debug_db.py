import asyncio
import os
import asyncpg
from urllib.parse import urlparse

async def debug_database():
    database_url = os.getenv('DATABASE_URL')
    print(f"Database URL exists: {bool(database_url)}")
    
    if database_url:
        parsed = urlparse(database_url)
        print(f"Host: {parsed.hostname}")
        print(f"Port: {parsed.port}")
        print(f"Database: {parsed.path[1:] if parsed.path else 'None'}")
        
        try:
            # Try to connect
            conn = await asyncpg.connect(database_url)
            
            # Test query to check quest data
            quest_count = await conn.fetchval("SELECT COUNT(*) FROM quests WHERE guild_id = 1266086795091906664")
            user_count = await conn.fetchval("SELECT COUNT(*) FROM leaderboard WHERE guild_id = 1266086795091906664")
            progress_count = await conn.fetchval("SELECT COUNT(*) FROM quest_progress WHERE guild_id = 1266086795091906664")
            
            print(f"Quests: {quest_count}")
            print(f"Users: {user_count}")
            print(f"Quest Progress: {progress_count}")
            
            # Check if there are any users with points
            max_points = await conn.fetchval("SELECT MAX(points) FROM leaderboard WHERE guild_id = 1266086795091906664")
            print(f"Max points: {max_points}")
            
            await conn.close()
            print("Connection successful!")
            
        except Exception as e:
            print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(debug_database())