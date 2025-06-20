import streamlit as st
import xml.etree.ElementTree as ET
from pykml import parser
import os
import math
from collections import defaultdict
import pandas as pd
from io import BytesIO
import re

# Set page config
st.set_page_config(
    page_title="KML Processing Tool",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Check for required Excel packages
try:
    import xlsxwriter
    EXCEL_ENGINE = 'xlsxwriter'
except ImportError:
    try:
        import openpyxl
        EXCEL_ENGINE = 'openpyxl'
    except ImportError:
        EXCEL_ENGINE = None

@st.cache_data
def calculate_distance(coord1, coord2):
    """Calculate distance between two coordinates (lon, lat) in meters using Haversine formula"""
    lon1, lat1 = coord1
    lon2, lat2 = coord2
    
    # Convert degrees to radians
    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)
    
    # Haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    radius_earth = 6371000  # Earth radius in meters
    distance = radius_earth * c
    
    return distance

@st.cache_data
def calculate_linestring_length(coordinates):
    """Calculate total length of LineString from coordinate list"""
    total_length = 0.0
    for i in range(len(coordinates)-1):
        coord1 = coordinates[i]
        coord2 = coordinates[i+1]
        total_length += calculate_distance(coord1, coord2)
    return total_length

def remove_encoding_declaration(xml_content):
    """Remove XML encoding declaration to avoid parsing issues"""
    return re.sub(r'^\s*<\?xml[^>]*\?>', '', xml_content, flags=re.MULTILINE).strip()

@st.cache_data
def process_kml_file(uploaded_file):
    """Process KML file and count all found labels"""
    counts = defaultdict(int)
    line_lengths = defaultdict(float)
    descriptions = defaultdict(list)
    
    try:
        # Read the uploaded file as bytes first
        content = uploaded_file.getvalue()
        
        try:
            # First try parsing as bytes directly
            doc = parser.fromstring(content)
        except:
            # If that fails, try decoding and removing encoding declaration
            decoded_content = content.decode('utf-8')
            cleaned_content = remove_encoding_declaration(decoded_content)
            doc = parser.fromstring(cleaned_content)
        
        # Find all Placemarks in the document
        placemarks = doc.findall('.//{http://www.opengis.net/kml/2.2}Placemark')
        if not placemarks:
            return counts, line_lengths, descriptions
            
        for pm in placemarks:
            name = pm.find('{http://www.opengis.net/kml/2.2}name')
            label = name.text.strip() if name is not None and name.text else "Unnamed"
            
            # Get description if available
            desc = pm.find('{http://www.opengis.net/kml/2.2}description')
            description = desc.text.strip() if desc is not None and desc.text else "No description"
            descriptions[label].append(description)
            
            # Process Polygon/Point
            if pm.find('.//{http://www.opengis.net/kml/2.2}Polygon') is not None:
                counts[f"{label} (Polygon)"] += 1
            elif pm.find('.//{http://www.opengis.net/kml/2.2}Point') is not None:
                counts[f"{label} (Point)"] += 1
            
            # Process LineString
            linestring = pm.find('.//{http://www.opengis.net/kml/2.2}LineString')
            if linestring is not None:
                coords = linestring.find('{http://www.opengis.net/kml/2.2}coordinates')
                if coords is not None and coords.text:
                    try:
                        coord_list = []
                        for coord_str in coords.text.strip().split():
                            parts = coord_str.split(',')
                            if len(parts) >= 2:
                                lon, lat = float(parts[0]), float(parts[1])
                                coord_list.append((lon, lat))
                        
                        if coord_list:
                            length = calculate_linestring_length(coord_list)
                            line_lengths[f"{label} (LineString)"] += length
                    except ValueError as e:
                        st.warning(f"Couldn't parse coordinates for {label}: {str(e)}")
    
    except ET.ParseError as e:
        st.error(f"XML parsing error: {str(e)}")
    except Exception as e:
        st.error(f"Error processing KML file: {str(e)}")
    
    return dict(counts), dict(line_lengths), dict(descriptions)

def display_results(counts, line_lengths, descriptions):
    """Display results in Streamlit"""
    st.subheader("📊 Processing Results")
    
    tab1, tab2 = st.tabs(["Feature Counts", "LineString Lengths"])
    
    with tab1:
        if counts:
            st.write("**Feature Counts by Label:**")
            df_counts = pd.DataFrame.from_dict(counts, orient='index', columns=['Count'])
            st.dataframe(df_counts.sort_values(by='Count', ascending=False))
            
            st.write("**Sample Descriptions:**")
            try:
                displayed_labels = set()
                for i, (label, count) in enumerate(sorted(counts.items(), key=lambda x: x[1], reverse=True)):
                    if i >= 3:
                        break
                    clean_label = label.split(" (")[0]
                    if clean_label not in displayed_labels:
                        displayed_labels.add(clean_label)
                        desc_samples = descriptions.get(clean_label, ['No description'])[:3]
                        st.write(f"- **{clean_label}**: {', '.join(desc_samples)}")
            except Exception as e:
                st.warning(f"Couldn't display descriptions: {str(e)}")
        else:
            st.warning("No features found in the KML file")
    
    with tab2:
        if line_lengths:
            st.write("**LineString Lengths by Label (meters):**")
            df_lengths = pd.DataFrame.from_dict(line_lengths, orient='index', columns=['Length (m)'])
            df_lengths['Length (km)'] = (df_lengths['Length (m)'] / 1000).round(0)
            
            # Format numbers without decimals
            pd.options.display.float_format = '{:,.0f}'.format
            
            st.dataframe(df_lengths.sort_values(by='Length (m)', ascending=False))
        else:
            st.warning("No LineStrings found in the KML file")
    
    # Download buttons
    st.subheader("📥 Download Results")
    
    if counts or line_lengths:
        if EXCEL_ENGINE is None:
            st.warning("Excel export requires either xlsxwriter or openpyxl package. Showing data as CSV instead.")
            csv_data = pd.concat([
                pd.DataFrame.from_dict(counts, orient='index', columns=['Count']),
                pd.DataFrame.from_dict(line_lengths, orient='index', columns=['Length (m)'])
            ], axis=1).to_csv().encode('utf-8')
            
            st.download_button(
                label="Download CSV",
                data=csv_data,
                file_name="kml_results.csv",
                mime="text/csv"
            )
        else:
            # Create Excel file
            output = BytesIO()
            with pd.ExcelWriter(output, engine=EXCEL_ENGINE) as writer:
                if counts:
                    df_counts = pd.DataFrame.from_dict(counts, orient='index', columns=['Count'])
                    df_counts.to_excel(writer, sheet_name='Feature Counts')
                
                if line_lengths:
                    df_lengths = pd.DataFrame.from_dict(line_lengths, orient='index', columns=['Length (m)'])
                    df_lengths['Length (km)'] = (df_lengths['Length (m)'] / 1000).round(0)
                    df_lengths.to_excel(writer, sheet_name='LineString Lengths')
            
            st.download_button(
                label="Download Excel Report",
                data=output.getvalue(),
                file_name="kml_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

def main():
    st.title("🌍 KML Processing Tool")
    st.markdown("Upload a KML file to count features and calculate LineString lengths")
    
    uploaded_file = st.file_uploader("Choose a KML file", type=['kml'])
    
    if uploaded_file is not None:
        st.success(f"File uploaded: {uploaded_file.name}")
        
        with st.spinner("Processing KML file..."):
            counts, line_lengths, descriptions = process_kml_file(uploaded_file)
        
        display_results(counts, line_lengths, descriptions)
    else:
        st.info("Please upload a KML file to begin processing")

if __name__ == "__main__":
    main()
