import os 
from pydantic_settings import BaseSettings, SettingsConfigDict 
from dotenv import load_dotenv 
load_dotenv() 
class Settings(BaseSettings): 
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN") 
    SUPABASE_URL: str = os.getenv("SUPABASE_URL") 
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY") 
    BASE_URL: str=  "https://pinghook.dev"
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True) 
    
    
    
settings = Settings()

