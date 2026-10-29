"""Production HTTP launcher: python -m twin.hosting (PORT defaults to 10000)."""
import os


def main():
    import uvicorn
    port=int(os.environ.get("PORT","10000"))
    if not 1<=port<=65535:raise ValueError("PORT must be between 1 and 65535")
    uvicorn.run("twin.public_app:create_app",factory=True,host="0.0.0.0",port=port,
                workers=1,limit_concurrency=16,timeout_keep_alive=5,server_header=False,access_log=False)


if __name__=="__main__":main()
