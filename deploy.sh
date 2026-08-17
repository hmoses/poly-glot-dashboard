#!/bin/bash
# Run this once GitHub is back online
# Creates repo, pushes code, enables GitHub Pages

set -e

echo "🔍 Checking GitHub status..."
gh auth status 2>&1 || { echo "❌ Run: gh auth login"; exit 1; }

echo "📦 Creating repo..."
gh repo create poly-glot-dashboard --public --description "Real-time App Store analytics dashboard for Poly-Glot AI" || echo "Repo may already exist"

echo "🔗 Setting remote..."
cd /Users/haroldmoses/poly-glot-dashboard
git remote remove origin 2>/dev/null || true
git remote add origin https://github.com/hmoses/poly-glot-dashboard.git

echo "📤 Pushing code..."
git add -A
git commit -m "Add workflow file" 2>/dev/null || true
git push -u origin main --force

echo "🌐 Enabling GitHub Pages..."
gh api repos/hmoses/poly-glot-dashboard/pages -X POST -f "build_type=legacy" -f "source[branch]=main" -f "source[path]=/" 2>/dev/null || echo "Pages may already be enabled"

echo "🔑 Adding secrets..."
gh secret set ASC_KEY_ID -b "3M53HUUZF3" -R hmoses/poly-glot-dashboard
gh secret set ASC_ISSUER_ID -b "27273279-3df5-4fd7-b3f9-b6e882c1fc38" -R hmoses/poly-glot-dashboard
gh secret set ASC_REPORT_REQUEST_ID -b "f46b6fd5-272c-4b46-9a88-55b399ea11f0" -R hmoses/poly-glot-dashboard

echo "⚠️  You still need to manually add ASC_PRIVATE_KEY secret:"
echo "   gh secret set ASC_PRIVATE_KEY < ~/private_keys/AuthKey_3M53HUUZF3.p8 -R hmoses/poly-glot-dashboard"

echo ""
echo "✅ Done! Dashboard will be live at: https://hmoses.github.io/poly-glot-dashboard/"
echo "   GitHub Action will auto-update data every 6 hours."
