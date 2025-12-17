"""Setup script to verify Ollama installation and install deepseek-r1 model."""

import subprocess
import sys


def check_ollama_installed():
    """Check if Ollama is installed."""
    try:
        result = subprocess.run(["ollama", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✓ Ollama is installed: {result.stdout.strip()}")
            return True
        else:
            print("✗ Ollama is not installed or not in PATH")
            return False
    except FileNotFoundError:
        print("✗ Ollama is not installed or not in PATH")
        print("  Download from: https://ollama.com/download")
        return False


def check_model_installed(model_name="deepseek-r1:latest"):
    """Check if the model is installed."""
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
        if result.returncode == 0:
            models = result.stdout
            if model_name in models:
                print(f"✓ Model '{model_name}' is installed")
                return True
            else:
                print(f"✗ Model '{model_name}' is not installed")
                print(f"  Available models:")
                for line in models.split("\n")[1:]:  # Skip header
                    if line.strip():
                        print(f"    - {line.strip()}")
                return False
        else:
            print("✗ Could not list Ollama models")
            return False
    except Exception as e:
        print(f"✗ Error checking models: {str(e)}")
        return False


def install_model(model_name="deepseek-r1:latest"):
    """Install the model."""
    print(f"\nInstalling model '{model_name}'...")
    print("This may take a few minutes depending on your internet connection...")
    try:
        result = subprocess.run(["ollama", "pull", model_name], text=True)
        if result.returncode == 0:
            print(f"✓ Model '{model_name}' installed successfully!")
            return True
        else:
            print(f"✗ Failed to install model '{model_name}'")
            return False
    except Exception as e:
        print(f"✗ Error installing model: {str(e)}")
        return False


def check_python_library():
    """Check if ollama Python library is installed."""
    try:
        import ollama

        print("✓ Python 'ollama' library is installed")
        return True
    except ImportError:
        print("✗ Python 'ollama' library is not installed")
        print("  Install with: pip install ollama")
        return False


def main():
    """Main setup function."""
    print("=" * 60)
    print("Ollama Setup for NZZ Scraper")
    print("=" * 60)
    print()

    # Check Ollama installation
    if not check_ollama_installed():
        print("\nPlease install Ollama first from: https://ollama.com/download")
        sys.exit(1)

    print()

    # Check Python library
    python_ok = check_python_library()
    if not python_ok:
        print("\nInstalling Python 'ollama' library...")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "ollama"], check=True
            )
            print("✓ Python 'ollama' library installed")
            python_ok = True
        except Exception as e:
            print(f"✗ Failed to install Python library: {str(e)}")
            print("  Please install manually: pip install ollama")

    print()

    # Check model
    model_name = "deepseek-r1:latest"
    if not check_model_installed(model_name):
        response = input(f"\nWould you like to install '{model_name}' now? (y/n): ")
        if response.lower() == "y":
            if install_model(model_name):
                print("\n✓ Setup complete! You can now run the scraper.")
            else:
                print("\n✗ Setup incomplete. Please install the model manually:")
                print(f"  ollama pull {model_name}")
        else:
            print(f"\nPlease install the model manually:")
            print(f"  ollama pull {model_name}")
    else:
        print("\n✓ Setup complete! You can now run the scraper.")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
