const fs = require('fs');
const path = require('path');

const themeArg = (process.argv[2] || 'contract').toLowerCase();
const projectDir = path.resolve(__dirname, '..');
const pagesDir = path.join(projectDir, 'Project Review - Programme (datalake).Report', 'definition', 'pages');

const imageName = themeArg.includes('target') ? 'Target.png' : 'Contract.png';

const folders = fs.readdirSync(pagesDir).filter(f => fs.statSync(path.join(pagesDir, f)).isDirectory());

let updatedCount = 0;

folders.forEach(f => {
    const pfile = path.join(pagesDir, f, 'page.json');
    if (!fs.existsSync(pfile)) return;
    
    const content = JSON.parse(fs.readFileSync(pfile, 'utf8'));
    
    if (content.objects && content.objects.background && content.objects.background[0]) {
        const bg = content.objects.background[0].properties;
        
        bg.image = {
            image: {
                name: {
                    expr: {
                        Literal: {
                            Value: `'${imageName}'`
                        }
                    }
                },
                url: {
                    expr: {
                        ResourcePackageItem: {
                            PackageName: "RegisteredResources",
                            PackageType": 1,
                            ItemName: imageName
                        }
                    }
                },
                scaling: {
                    expr: {
                        Literal: {
                            Value: "'Fill'"
                        }
                    }
                }
            }
        };
        
        bg.transparency = {
            expr: {
                Literal: {
                    Value: "0D"
                }
            }
        };
        
        fs.writeFileSync(pfile, JSON.stringify(content, null, 2), 'utf8');
        updatedCount++;
    }
});

console.log(`Successfully updated ${updatedCount} pages to background '${imageName}' with scaling 'Fill'.`);
