{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  buildInputs = [
    (pkgs.python3.withPackages (ps: with ps; [
      flask
      flask-cors
    ]))
    pkgs.sqlite
  ];

  shellHook = ''
    echo "=========================================================="
    echo "Welcome to the Mapbox GL + Python + SQLite project shell!"
    echo "Python version: $(python --version)"
    echo "SQLite version: $(sqlite3 --version)"
    echo "=========================================================="
    
    read -p "Would you like to run the website now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Starting the Python server..."
        python backend/server.py
    else
        echo "You are now in the nix shell."
        echo "To run the server later, run 'python backend/server.py'."
    fi
  '';
}
