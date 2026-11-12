"""Public entry point for the original-name, full-strict PDB loader."""
if __package__:
    from .loader_native import main
else:
    from loader_native import main

if __name__ == '__main__':
    main()
