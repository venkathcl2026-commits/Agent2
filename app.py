import os
import re
from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

app = Flask(__name__)

# Ensure output directory exists
os.makedirs('output', exist_ok=True)

def strip_html(html_content):
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text()

def clean_filename(title):
    # Remove invalid characters for Windows/Linux filenames
    return re.sub(r'[\\/*?:"<>|]', "", title).strip()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    data = request.json
    
    org = data.get('organization')
    project = data.get('project')
    work_item_id = data.get('workItemId')
    ado_pat = data.get('adoPat')
    openai_key = data.get('openaiKey')
    
    if not all([org, project, work_item_id, ado_pat, openai_key]):
        return jsonify({'error': 'All fields are required.'}), 400
        
    # Fetch work item from ADO
    ado_url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{work_item_id}?api-version=7.1"
    
    try:
        response = requests.get(ado_url, auth=('', ado_pat))
        if response.status_code != 200:
            return jsonify({'error': f"Failed to fetch work item from ADO. Status: {response.status_code}. Response: {response.text}"}), response.status_code
            
        work_item_data = response.json()
        fields = work_item_data.get('fields', {})
        title = fields.get('System.Title', f'WorkItem_{work_item_id}')
        acceptance_criteria = fields.get('Microsoft.VSTS.Common.AcceptanceCriteria', '')
        
        # Strip HTML tags from acceptance criteria
        clean_ac = strip_html(acceptance_criteria)
        
        if not clean_ac:
            return jsonify({'error': 'Acceptance Criteria is empty for this work item.'}), 400
            
    except Exception as e:
        return jsonify({'error': f"Error connecting to Azure DevOps: {str(e)}"}), 500

    # Generate Gherkin scenarios with OpenAI
    try:
        client = OpenAI(api_key=openai_key)
        
        prompt = f"""
I have an Azure DevOps work item titled "{title}".
The Acceptance Criteria is:
{clean_ac}

Please generate a Gherkin feature file for this work item.
- Create at least 5 test cases.
- Include both POSITIVE and NEGATIVE test cases.
- Format the output strictly in standard Gherkin syntax (Feature, Scenario, Given, When, Then).
- Do not include any markdown code blocks (like ```gherkin), just output the raw Gherkin text.
"""
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert QA engineer and BDD specialist."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        gherkin_content = completion.choices[0].message.content.strip()
        # Remove ```gherkin or ``` if the model accidentally included it
        gherkin_content = re.sub(r'^```[\w]*\n|\n```$', '', gherkin_content).strip()
        
        # Save to file
        safe_title = clean_filename(title)
        filename = f"{safe_title}.feature"
        filepath = os.path.join('output', filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(gherkin_content)
            
        return jsonify({
            'success': True,
            'message': 'Feature file generated successfully.',
            'title': title,
            'filename': filename,
            'content': gherkin_content,
            'filepath': filepath
        })
        
    except Exception as e:
        return jsonify({'error': f"Error generating testing cases with OpenAI: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
